"""Path-allowlist enforcement for ``ds_*`` tools.

Mirrors the algorithm in ``irods-mcp-server/irods/common/permission.go`` and
``path.go``: build the caller's accessible path set (home + shared + ticket-
granted) and walk the request path against it. Everything in this module is
deliberately a pure function so handlers can unit-test their access semantics
without spinning up an iRODS session.

The normalised path returned from :func:`assert_allowed` should be used by
callers in place of the raw input — it collapses ``//`` runs, resolves ``.``
and ``..`` segments, and strips trailing slashes, so the iRODS path the
handler hands to ``python-irodsclient`` is the same one that was access-
checked.
"""

from __future__ import annotations

import posixpath

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.errors import ToolError


def normalize(path: str) -> str:
    """Normalise an iRODS logical path.

    Steps:

    1. Strip a leading ``i:`` (icommands compatibility, matches the Go code).
    2. Reject empty / whitespace-only paths.
    3. Reject relative paths — every iRODS logical path in mesa-mcp is
       absolute (the auth-aware home-expansion that ``MakeIRODSPath`` does
       in the Go code lives at the handler level, not here).
    4. Collapse runs of ``/``, resolve ``.`` and ``..`` segments via
       :func:`posixpath.normpath`. Because the path is absolute,
       ``normpath`` clamps ``..`` at the root — ``/..`` becomes ``/``.
    5. Strip trailing ``/`` (except for the root ``/``).
    """
    if path is None:
        raise ToolError(
            code="invalid_argument",
            message="iRODS path must not be None.",
        )

    stripped = path.strip()
    if not stripped:
        raise ToolError(
            code="invalid_argument",
            message="iRODS path must not be empty.",
        )

    # icommands compat — `i:/zone/home/...`
    if stripped.startswith("i:"):
        stripped = stripped[2:]

    if not stripped.startswith("/"):
        raise ToolError(
            code="invalid_argument",
            message=f"iRODS path must be absolute, got {path!r}.",
            details={"path": path},
        )

    # posixpath.normpath, given an absolute path, collapses ``//`` runs
    # and resolves ``.`` / ``..`` segments. A leading ``..`` that would
    # walk above root is silently dropped — so ``/..`` returns ``/``.
    # POSIX preserves a leading double-slash (SMB-style), which iRODS
    # has no use for, so we collapse it explicitly first.
    while stripped.startswith("//"):
        stripped = stripped[1:]
    normalised = posixpath.normpath(stripped)

    # Trim trailing slash (only possible for root, which normpath already
    # collapses to '/'). Defensive trim in case the implementation evolves.
    if len(normalised) > 1 and normalised.endswith("/"):
        normalised = normalised.rstrip("/")
    return normalised


def is_within(path: str, root: str) -> bool:
    """Return True if ``path`` lies inside ``root`` (after normalisation).

    A path is "within" a root when it is equal to the root or starts with
    ``root + "/"``. Pure prefix matching would let ``/iplant/home/alice2``
    sneak in under ``/iplant/home/alice``; the trailing-slash form prevents
    that.
    """
    if path == root:
        return True
    if not root.endswith("/"):
        root = root + "/"
    return path.startswith(root)


def assert_allowed(path: str, auth_value: AuthValue) -> str:
    """Raise unless ``path`` falls within ``auth_value.accessible_paths()``.

    Returns the normalised path on success. Callers should bind the return
    value and use it in place of the original — that way handlers can never
    accidentally drift off the access-checked path.
    """
    normalised = normalize(path)

    for root in auth_value.accessible_paths():
        normalised_root = normalize(root)
        if is_within(normalised, normalised_root):
            return normalised

    raise ToolError(
        code="forbidden",
        message=(
            f"Path {normalised!r} is not within the caller's accessible "
            f"paths."
        ),
        details={"path": path, "user": auth_value.username},
    )
