"""Pooled ``iRODSSession`` accessor.

Python counterpart of ``irods-mcp-server/irods/common/irodsfs_pool.go``. The
Go pool caches one ``*irodsclient_fs.FileSystem`` per username with TTL
eviction; we cache one ``iRODSSession`` per auth-value :meth:`cache_key`
with LRU eviction (TTL semantics are not currently needed — the iRODS
server independently expires idle connections via its own pool).

Concurrency: ``python-irodsclient`` sessions own a TCP connection pool that
is not safe to use across event-loop iterations on the same connection
concurrently. We guard all cache mutation with a :class:`threading.Lock` so
that two tool handlers racing for the same caller's session do not both open
a fresh session and clobber the cache. Once a session is handed out, the
caller drives it within their own awaitable — that's the standard
``python-irodsclient`` usage pattern.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from irods.session import iRODSSession

from mesa_mcp.auth import build_account
from mesa_mcp.auth.models import AuthValue

if TYPE_CHECKING:
    from mesa_mcp.config import Config

logger = logging.getLogger(__name__)


DEFAULT_MAX_ENTRIES = 32


class IRODSClientPool:
    """LRU cache of authenticated ``iRODSSession`` objects, keyed by caller.

    Parameters
    ----------
    max_entries:
        Maximum number of distinct sessions held in the cache. When full, the
        oldest entry (by last-access order) is :meth:`iRODSSession.cleanup`-ed
        and dropped before a new session is inserted.
    config:
        Optional :class:`mesa_mcp.config.Config`. When supplied, the pool's
        :meth:`get` derives ``host`` and ``port`` from it; callers that need a
        different host (e.g. ticket-mediated sessions pointed at a relay) can
        pass explicit ``host``/``port`` kwargs to :meth:`get`.
    """

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        *,
        config: Config | None = None,
        session_factory: Any | None = None,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._config = config
        # ``session_factory`` is exposed for tests so they can substitute a
        # ``MagicMock`` without monkey-patching ``irods.session.iRODSSession``.
        # Production callers leave it ``None`` and get the real session class.
        self._session_factory = session_factory or iRODSSession
        self._cache: OrderedDict[str, iRODSSession] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(
        self,
        auth_value: AuthValue,
        *,
        host: str | None = None,
        port: int | None = None,
    ) -> iRODSSession:
        """Return a cached or freshly built session for ``auth_value``.

        Cache hits update LRU order. Misses build an :class:`iRODSAccount`
        via :func:`mesa_mcp.auth.build_account`, open an :class:`iRODSSession`
        from its keyword fields, and insert it under the auth value's
        :meth:`AuthValue.cache_key`.

        Raises
        ------
        ValueError
            If neither ``host``/``port`` are supplied nor a config was
            attached to the pool at construction.
        """
        key = auth_value.cache_key()

        with self._lock:
            existing = self._cache.get(key)
            if existing is not None:
                # LRU bump.
                self._cache.move_to_end(key)
                return existing

            resolved_host, resolved_port = self._resolve_endpoint(host, port)
            account = build_account(
                auth_value,
                host=resolved_host,
                port=resolved_port,
            )
            session = self._build_session(account)

            self._cache[key] = session
            self._cache.move_to_end(key)
            self._evict_if_needed_locked()
            return session

    def close(self) -> None:
        """Tear down every cached session and clear the cache."""
        with self._lock:
            for key, session in list(self._cache.items()):
                _safe_cleanup(session, key)
            self._cache.clear()

    # ------------------------------------------------------------------
    # Context-manager sugar
    # ------------------------------------------------------------------

    def __enter__(self) -> IRODSClientPool:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Introspection (for tests)
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def __contains__(self, auth_value: AuthValue) -> bool:
        with self._lock:
            return auth_value.cache_key() in self._cache

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_endpoint(
        self,
        host: str | None,
        port: int | None,
    ) -> tuple[str, int]:
        if host is not None and port is not None:
            return host, port
        if self._config is None:
            raise ValueError(
                "IRODSClientPool.get requires either explicit host/port arguments "
                "or a Config supplied at construction time."
            )
        return self._config.irods.host, self._config.irods.port

    def _build_session(self, account: Any) -> iRODSSession:
        """Build an ``iRODSSession`` from an ``iRODSAccount``-like object.

        ``python-irodsclient``'s :class:`iRODSSession` doesn't accept an
        ``iRODSAccount`` instance directly — it takes the same keyword
        arguments and reconstructs one internally. We extract the fields the
        session cares about and forward them. This keeps the pool decoupled
        from the account-construction details (handy when ``build_account``
        gains, e.g., ticket support).
        """
        kwargs: dict[str, Any] = {
            "host": account.host,
            "port": account.port,
            "user": account.client_user,
            "zone": account.client_zone,
            "password": account.password or "",
            "authentication_scheme": account.authentication_scheme,
        }
        return self._session_factory(**kwargs)

    def _evict_if_needed_locked(self) -> None:
        """LRU eviction; caller holds ``self._lock``."""
        while len(self._cache) > self._max_entries:
            evicted_key, evicted_session = self._cache.popitem(last=False)
            _safe_cleanup(evicted_session, evicted_key)


def _safe_cleanup(session: Any, key: str) -> None:
    """Call ``session.cleanup()`` swallowing any teardown errors.

    The iRODS Python client raises :class:`NetworkException` if the remote
    has already disconnected — we don't want a tear-down to crash the pool
    when the underlying TCP connection has gone away independently.
    """
    cleanup = getattr(session, "cleanup", None)
    if cleanup is None:
        return
    try:
        cleanup()
    except Exception:  # pragma: no cover - defensive
        logger.warning(
            "iRODS session cleanup failed",
            extra={"cache_key_prefix": key[:8]},
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_pool: IRODSClientPool | None = None


def default_pool() -> IRODSClientPool:
    """Return the process-wide :class:`IRODSClientPool`, building one on first call.

    ``ds_*`` tool handlers look up sessions via this accessor so a single
    cache is shared across every iRODS-touching tool. Tests can substitute
    a pre-built pool via :func:`set_default_pool` before invoking handlers.
    """
    global _default_pool
    if _default_pool is None:
        # Lazy config import to avoid a circular dependency at module load
        # time (``mesa_mcp.config`` imports ``mesa_mcp`` which imports us).
        from mesa_mcp.config import load_config

        _default_pool = IRODSClientPool(config=load_config())
    return _default_pool


def set_default_pool(pool: IRODSClientPool | None) -> None:
    """Replace (or clear) the module-level pool singleton. Test-only injection."""
    global _default_pool
    _default_pool = pool
