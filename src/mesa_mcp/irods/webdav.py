"""WebDAV URL minting helpers.

Python port of the URL minting logic in
``irods-mcp-server/irods/common/irods_client.go``. The CyVerse data store
exposes a WebDAV gateway at ``https://data.cyverse.org/dav/`` (configurable
via :attr:`IRODSConfig.webdav_url`) and every ``ds_*`` tool that surfaces an
iRODS path in its output also embeds a WebDAV URL so a client can fetch the
object over HTTPS without re-authenticating to iRODS proper.

The Go reference mints two flavours: a per-user URL with the caller's
username baked in as ``userinfo``, and an anonymous URL used when (a) the
caller themselves is anonymous, or (b) the object is anonymously readable.
This module preserves both shapes byte-for-byte; the ``accesses`` list lets
callers consult ACLs to decide which one to emit.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from mesa_mcp.auth.models import ANONYMOUS_USER, AuthValue


def _encode_path_segments(irods_path: str) -> str:
    """Percent-encode each path segment, mirroring ``url.PathEscape`` in Go.

    The Go reference trims surrounding ``/`` then joins percent-encoded
    segments with ``/``. An empty / root-only path encodes to ``""``.
    """
    trimmed = irods_path.strip("/")
    if not trimmed:
        return ""
    return "/".join(quote(segment, safe="") for segment in trimmed.split("/"))


def make_webdav_url_for_user(
    base_url: str,
    irods_path: str,
    user: str,
) -> str:
    """Mint a WebDAV URL with a specific user baked into the userinfo.

    Mirrors ``MakeWebdavURLForUser`` in the Go reference. ``base_url`` is
    the configured ``IRODSConfig.webdav_url`` value (e.g.
    ``"https://data.cyverse.org/dav/"``). Returns an empty string when the
    base URL is empty so callers can no-op gracefully.
    """
    if not base_url:
        return ""

    split = urlsplit(base_url)
    if not split.scheme or not split.netloc:
        # Malformed — match Go behaviour and return empty.
        return ""

    # Build userinfo + host so that anonymous users get the canonical
    # ``anonymous:@host`` form (empty password) and named users get
    # ``user@host``. The Go reference uses ``url.UserPassword("anonymous",
    # "")`` for anonymous and ``url.User(user)`` for everyone else.
    host = split.hostname or ""
    if split.port is not None:
        host = f"{host}:{split.port}"

    if user == ANONYMOUS_USER:
        userinfo = "anonymous:"
    elif user:
        userinfo = quote(user, safe="")
    else:
        userinfo = ""

    netloc = f"{userinfo}@{host}" if userinfo else host

    encoded_path = _encode_path_segments(irods_path)
    base_path = split.path.rstrip("/")
    if encoded_path:
        new_path = f"{base_path}/{encoded_path}" if base_path else f"/{encoded_path}"
    else:
        new_path = base_path or "/"

    return urlunsplit((split.scheme, netloc, new_path, split.query, split.fragment))


def make_webdav_url(
    base_url: str,
    irods_path: str,
    auth_value: AuthValue,
) -> str:
    """Mint a WebDAV URL using the caller identity, defaulting to anonymous.

    Mirrors ``MakeWebdavURL`` in the Go reference: an anonymous caller (or
    a missing :class:`AuthValue`) always gets the anonymous URL; otherwise
    the caller's iRODS username is embedded.
    """
    if auth_value is None or auth_value.is_anonymous():
        return make_webdav_url_for_user(base_url, irods_path, ANONYMOUS_USER)
    return make_webdav_url_for_user(base_url, irods_path, auth_value.username)


def make_webdav_url_with_accesses(
    base_url: str,
    irods_path: str,
    auth_value: AuthValue,
    accesses: list[Any] | None,
) -> str:
    """Mint a WebDAV URL, preferring the anonymous form for public objects.

    Mirrors ``MakeWebdavURLWithAccesses`` in the Go reference. ``accesses``
    is a list of access records (``iRODSAccess`` objects from
    ``python-irodsclient``, or duck-typed objects with a ``.user_name``
    attribute). If any entry grants the ``anonymous`` user read access on
    this path, the URL is minted as anonymous so it can be shared without
    leaking the caller's identity.
    """
    if auth_value is None or auth_value.is_anonymous():
        return make_webdav_url_for_user(base_url, irods_path, ANONYMOUS_USER)

    if accesses:
        for access in accesses:
            user_name = getattr(access, "user_name", None)
            if user_name == ANONYMOUS_USER:
                return make_webdav_url_for_user(
                    base_url,
                    irods_path,
                    ANONYMOUS_USER,
                )

    return make_webdav_url_for_user(base_url, irods_path, auth_value.username)


def make_resource_uri(irods_path: str) -> str:
    """Build the ``irods://`` resource URI used in tool outputs.

    Mirrors ``MakeResourceURI`` in ``irods/common/resource.go``.
    """
    return f"irods://{irods_path}"
