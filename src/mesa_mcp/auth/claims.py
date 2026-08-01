"""Typed view of the CyVerse Keycloak JWT payload.

Identity extraction previously lived inline in two places — the OIDC
verifier and the trusted-decode header path — each reaching into the raw
claims dict. This module is the single place that decides *who a token
says you are*, so a change to that mapping happens once.

Modelled on the equivalent in `cyverse-de/formation`, which draws the same
distinctions (``preferred_username`` falling back to ``sub``, a display
name assembled from ``name`` or given/family, explicit service-account
detection). Two deliberate differences:

* fields are ``str | None`` rather than pointers, and :meth:`username`
  treats an empty string the same as an absent claim — a token carrying
  ``"preferred_username": ""`` must not authenticate as the empty user;
* the CyVerse realm suffix (``alice@CyVerse``) is stripped here, because
  iRODS usernames carry no realm.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

#: Keycloak names a client's service account
#: ``service-account-<client-id>``. Such a token authenticates a *client*,
#: not a person.
SERVICE_ACCOUNT_PREFIX = "service-account-"


class KeycloakClaims(BaseModel):
    """The subset of a Keycloak access token that mesa-mcp reads.

    Construct with :meth:`from_payload`; the raw claims dict is preserved
    on :attr:`raw` for anything not modelled here.
    """

    model_config = ConfigDict(frozen=True)

    sub: str | None = None
    preferred_username: str | None = None
    email: str | None = None
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    exp: int | None = None
    raw: dict[str, Any] = {}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> KeycloakClaims:
        """Build from a decoded JWT payload, keeping the original dict."""

        def _str(key: str) -> str | None:
            value = payload.get(key)
            return value if isinstance(value, str) else None

        exp = payload.get("exp")
        return cls(
            sub=_str("sub"),
            preferred_username=_str("preferred_username"),
            email=_str("email"),
            name=_str("name"),
            given_name=_str("given_name"),
            family_name=_str("family_name"),
            exp=exp if isinstance(exp, int) else None,
            raw=dict(payload),
        )

    @property
    def is_service_account(self) -> bool:
        """True when the token belongs to a Keycloak *client*, not a person.

        These must not reach iRODS: the ``service-account-<client>`` string
        would be used as an iRODS username, so ACL evaluation would run
        against a principal that does not exist — failing far from the
        cause, or worse, matching an unrelated account someone later
        creates under that name.
        """
        return (self.preferred_username or "").startswith(SERVICE_ACCOUNT_PREFIX)

    def username(self) -> str | None:
        """Identity for iRODS: ``preferred_username``, falling back to ``sub``.

        Returns ``None`` when the token carries neither, so the caller
        decides how to fail. The CyVerse realm suffix is stripped —
        ``alice@CyVerse`` is the iRODS user ``alice``.
        """
        raw = (self.preferred_username or "").strip() or (self.sub or "").strip()
        if not raw:
            return None
        return raw.split("@", 1)[0] or None

    def display_name(self) -> str:
        """Human-readable name: ``name``, else given + family, else ``""``."""
        if self.name:
            return self.name
        parts = [p for p in (self.given_name, self.family_name) if p]
        return " ".join(parts)

    def expiry(self) -> datetime | None:
        """``exp`` as an aware UTC datetime, or ``None`` when absent."""
        if self.exp is None:
            return None
        return datetime.fromtimestamp(self.exp, tz=UTC)
