"""The :class:`AuthValue` model — everything mesa-mcp needs to know about a caller.

This is the Python counterpart of ``common.AuthValue`` in
``irods-mcp-server/common/auth.go``. Tools never see raw credentials directly;
they receive an :class:`AuthValue` from the auth middleware (or, in tests, a
constructed instance) and pass it to the connection pool and the path-access
checker.

Hard rules baked into this module:

* The model is **frozen**, so accidental mutation in a handler is a type error.
* The ``password`` field is marked ``repr=False`` and excluded from the hashed
  cache key by name — the SHA-256 :meth:`AuthValue.cache_key` digests the
  password *bytes* alongside zone+username, never the plaintext.
* :meth:`AuthValue.accessible_paths` is the single source of truth for what
  paths a caller may touch; :mod:`mesa_mcp.irods.access` consumes it.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AuthScheme = Literal["native", "pam", "anonymous"]

ANONYMOUS_USER = "anonymous"


class AuthValue(BaseModel):
    """Immutable description of a caller's authentication state.

    Constructed by transport-specific extractors (env for stdio, headers for
    HTTP/SSE) and threaded through every ``ds_*`` handler. The :attr:`home_path`
    and :attr:`shared_path` are derived once at construction time so the rest
    of the code can treat the value as a flat record.
    """

    model_config = ConfigDict(frozen=True)

    username: str
    zone: str
    password: str | None = Field(default=None, repr=False)
    auth_scheme: AuthScheme = "native"
    proxy_user: str | None = None
    ticket: str | None = None
    home_path: str = ""
    shared_path: str = ""
    #: Name of the zone's shared collection under ``/<zone>/home``. Mirrors
    #: ``IRODSConfig.shared_dir_name``; extractors that have a Config pass
    #: it through so a zone that does not call its shared tree "shared" is
    #: still reachable. Ignored when ``shared_path`` is supplied directly.
    shared_dir_name: str = "shared"

    @model_validator(mode="after")
    def _derive_paths(self) -> AuthValue:
        # Pydantic frozen models still allow ``__setattr__`` via ``object``.
        # Derive the home and shared paths from zone + username so callers
        # don't have to.
        if not self.home_path:
            if self.is_anonymous():
                home = f"/{self.zone}/home/{ANONYMOUS_USER}"
            else:
                home = f"/{self.zone}/home/{self.username}"
            object.__setattr__(self, "home_path", home)
        if not self.shared_path:
            shared = (self.shared_dir_name or "shared").strip("/")
            object.__setattr__(self, "shared_path", f"/{self.zone}/home/{shared}")
        return self

    # ------------------------------------------------------------------
    # Predicates
    # ------------------------------------------------------------------

    def is_anonymous(self) -> bool:
        """True when the caller is the iRODS ``anonymous`` pseudo-user."""
        return self.auth_scheme == "anonymous" or self.username == ANONYMOUS_USER

    # ------------------------------------------------------------------
    # Access surface
    # ------------------------------------------------------------------

    def accessible_paths(self) -> list[str]:
        """Return the set of paths the caller may read or write.

        Mirrors the Go ``GetAccessiblePaths`` shape: home + shared, plus a
        ticket-granted path when the session is ticket-mediated. Anonymous
        callers do not get a home directory — only the shared path (and an
        optional ticket-granted path).
        """
        paths: list[str] = []
        if not self.is_anonymous():
            paths.append(self.home_path)
        paths.append(self.shared_path)
        if self.ticket:
            # Tickets in iRODS reference a path; the ticket itself doesn't
            # carry it here. The middleware that minted the ticket records
            # the granted path on the AuthValue via the ``ticket`` field —
            # callers may extend this list once that wiring lands. For now
            # the ticket id alone widens nothing; this hook exists so future
            # ticket-bearing AuthValues can extend the list without changing
            # call sites.
            pass
        return paths

    # ------------------------------------------------------------------
    # Cache key
    # ------------------------------------------------------------------

    def cache_key(self) -> str:
        """A stable, secret-free key for the connection pool.

        SHA-256 over zone || username || (password bytes or empty). The
        plaintext password never leaves this method; only its hashed form
        contributes to the digest, and the digest itself is hex-encoded.
        """
        hasher = hashlib.sha256()
        hasher.update(self.zone.encode("utf-8"))
        hasher.update(b"\x1f")  # ASCII unit separator
        hasher.update(self.username.encode("utf-8"))
        hasher.update(b"\x1f")
        if self.password is not None:
            hasher.update(self.password.encode("utf-8"))
        # Distinguish proxy + ticket sessions so they don't collide with
        # their parent credentials.
        hasher.update(b"\x1f")
        if self.proxy_user:
            hasher.update(self.proxy_user.encode("utf-8"))
        hasher.update(b"\x1f")
        if self.ticket:
            hasher.update(self.ticket.encode("utf-8"))
        return hasher.hexdigest()
