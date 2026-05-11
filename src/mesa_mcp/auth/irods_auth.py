"""Bridge between :class:`AuthValue` and ``python-irodsclient``'s account object.

The Go reference splits this across ``irods-mcp-server/irods/irods.go``'s
``GetIRODSAccountFromAuthValue`` and ``irods/common/irods_client.go``'s
``GetEmptyIRODSAccount`` helper. We collapse them into one function here: take
an :class:`AuthValue` plus enough connection info (host/port) from the running
:class:`mesa_mcp.config.Config`, return a fully-populated ``iRODSAccount``.

The connection pool consumes the resulting account to open a session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from irods.account import iRODSAccount

from .models import AuthValue

if TYPE_CHECKING:
    from mesa_mcp.config import Config


def build_account(
    auth_value: AuthValue,
    *,
    host: str,
    port: int,
) -> iRODSAccount:
    """Construct an ``iRODSAccount`` from an :class:`AuthValue`.

    Parameters
    ----------
    auth_value:
        Caller credentials and zone information.
    host:
        iRODS server hostname (from :class:`mesa_mcp.config.IRODSConfig`).
    port:
        iRODS server port (typically 1247).

    Returns
    -------
    iRODSAccount
        A populated account ready to be handed to ``iRODSSession``. For the
        anonymous case the password is empty and ``irods_authentication_scheme``
        is forced to ``anonymous`` per iRODS conventions.

    Notes
    -----
    Native and PAM differ only in the ``irods_authentication_scheme`` field;
    the password is supplied the same way in both cases. The proxy_user case
    (admin acting on behalf of another user) sets ``client_user`` to the
    target user and keeps ``proxy_user`` as the authenticated admin.
    """
    if auth_value.is_anonymous():
        return iRODSAccount(
            irods_host=host,
            irods_port=port,
            irods_user_name=auth_value.username or "anonymous",
            irods_zone_name=auth_value.zone,
            irods_authentication_scheme="anonymous",
            password="",
        )

    scheme = auth_value.auth_scheme
    # ``python-irodsclient`` recognises ``native`` and ``pam`` (and a few
    # aliases); pass it straight through.
    account = iRODSAccount(
        irods_host=host,
        irods_port=port,
        irods_user_name=auth_value.username,
        irods_zone_name=auth_value.zone,
        irods_authentication_scheme=scheme,
        password=auth_value.password or "",
    )

    if auth_value.proxy_user:
        # The authenticated user is the proxy; the target client user is what
        # was supplied in the AuthValue.
        account.proxy_user = auth_value.proxy_user
        account.proxy_zone = auth_value.zone
        account.client_user = auth_value.username
        account.client_zone = auth_value.zone

    return account


def build_account_from_config(
    auth_value: AuthValue,
    config: Config,
) -> iRODSAccount:
    """Convenience wrapper: pull ``host``/``port`` from the global config."""
    return build_account(
        auth_value,
        host=config.irods.host,
        port=config.irods.port,
    )


def build_account_from_oidc(
    auth_value: AuthValue,
    config: Config,
) -> iRODSAccount:
    """Stub: build an ``iRODSAccount`` for an OIDC-authenticated caller.

    Keycloak tokens identify a user but don't carry the user's iRODS
    password. Until proxy-auth / ticket-mediated sessions land, we fall
    back to the **service-account password** in ``config.irods.password``
    so the iRODS client pool can still open a session. This is
    intentionally narrow: the iRODS server-side ACLs are still the source
    of truth for what the OIDC-authenticated user may touch — the
    service account is just the transport.

    A real proxy-auth flow (admin acting on behalf of the OIDC user)
    lands when :class:`mesa_mcp.irods.client_pool.IRODSClientPool` gains
    a ``proxy_user`` branch; until then ``auth_value.proxy_user`` is
    expected to be ``None`` here.
    """
    proxied = auth_value.model_copy(
        update={"password": config.irods.password},
    )
    return build_account_from_config(proxied, config)
