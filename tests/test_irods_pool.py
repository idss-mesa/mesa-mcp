"""Unit tests for :class:`mesa_mcp.irods.client_pool.IRODSClientPool`.

Mocks the ``iRODSSession`` factory so no TCP connection is opened.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mesa_mcp.auth import AuthValue
from mesa_mcp.config import Config
from mesa_mcp.irods.client_pool import IRODSClientPool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(name: str = "session") -> MagicMock:
    """Return a MagicMock that quacks like an ``iRODSSession`` for our tests."""
    session = MagicMock(name=name)
    session.cleanup = MagicMock(name=f"{name}.cleanup")
    return session


def _make_pool(
    *,
    max_entries: int = 32,
    sessions: list[MagicMock] | None = None,
) -> tuple[IRODSClientPool, MagicMock]:
    """Build a pool whose ``session_factory`` yields prebuilt mocks in order."""
    sessions = sessions or []
    factory_calls: list[dict[str, object]] = []

    def factory(**kwargs: object) -> MagicMock:
        factory_calls.append(kwargs)
        if sessions:
            return sessions.pop(0)
        return _make_session(f"session-{len(factory_calls)}")

    factory_mock = MagicMock(side_effect=factory)
    pool = IRODSClientPool(
        max_entries=max_entries,
        config=Config(),
        session_factory=factory_mock,
    )
    return pool, factory_mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_caches_session_for_same_auth_value():
    pool, factory = _make_pool()
    av = AuthValue(username="alice", zone="iplant", password="hunter2")

    s1 = pool.get(av)
    s2 = pool.get(av)

    assert s1 is s2
    factory.assert_called_once()


def test_distinct_auth_values_get_distinct_sessions():
    pool, factory = _make_pool()
    alice = AuthValue(username="alice", zone="iplant", password="hunter2")
    bob = AuthValue(username="bob", zone="iplant", password="hunter2")

    s_alice = pool.get(alice)
    s_bob = pool.get(bob)

    assert s_alice is not s_bob
    assert factory.call_count == 2


def test_lru_eviction_closes_oldest():
    sessions = [_make_session(f"s{i}") for i in range(3)]
    pool, _factory = _make_pool(max_entries=2, sessions=sessions)
    a = AuthValue(username="a", zone="iplant", password="pw")
    b = AuthValue(username="b", zone="iplant", password="pw")
    c = AuthValue(username="c", zone="iplant", password="pw")

    s_a = pool.get(a)
    s_b = pool.get(b)
    # Insert a third; ``s_a`` is the oldest and should be evicted.
    s_c = pool.get(c)

    assert len(pool) == 2
    assert a not in pool
    assert b in pool
    assert c in pool
    s_a.cleanup.assert_called_once()
    s_b.cleanup.assert_not_called()
    s_c.cleanup.assert_not_called()


def test_cache_hit_refreshes_lru_order():
    sessions = [_make_session(f"s{i}") for i in range(3)]
    pool, _factory = _make_pool(max_entries=2, sessions=sessions)
    a = AuthValue(username="a", zone="iplant", password="pw")
    b = AuthValue(username="b", zone="iplant", password="pw")
    c = AuthValue(username="c", zone="iplant", password="pw")

    s_a = pool.get(a)
    s_b = pool.get(b)
    # Touch ``a`` to bump it ahead of ``b`` in the LRU ordering.
    pool.get(a)
    # Insert c — now ``b`` is the oldest and should be evicted, not ``a``.
    pool.get(c)

    assert a in pool
    assert c in pool
    assert b not in pool
    s_b.cleanup.assert_called_once()
    s_a.cleanup.assert_not_called()


def test_close_cleans_up_all_sessions_and_empties_cache():
    sessions = [_make_session(f"s{i}") for i in range(2)]
    pool, _factory = _make_pool(sessions=sessions)
    a = AuthValue(username="a", zone="iplant", password="pw")
    b = AuthValue(username="b", zone="iplant", password="pw")

    s_a = pool.get(a)
    s_b = pool.get(b)

    pool.close()

    s_a.cleanup.assert_called_once()
    s_b.cleanup.assert_called_once()
    assert len(pool) == 0


def test_close_is_idempotent():
    pool, _factory = _make_pool()
    pool.get(AuthValue(username="a", zone="iplant", password="pw"))
    pool.close()
    pool.close()  # should not raise


def test_context_manager_closes_on_exit():
    sessions = [_make_session("only")]
    pool, _factory = _make_pool(sessions=sessions)
    a = AuthValue(username="a", zone="iplant", password="pw")

    with pool:
        s = pool.get(a)
        assert len(pool) == 1
    s.cleanup.assert_called_once()
    assert len(pool) == 0


def test_get_requires_config_or_explicit_endpoint():
    factory = MagicMock(side_effect=lambda **_: _make_session())
    pool = IRODSClientPool(session_factory=factory)  # no config supplied
    a = AuthValue(username="a", zone="iplant", password="pw")
    with pytest.raises(ValueError):
        pool.get(a)


def test_get_with_explicit_host_port_overrides_config():
    pool, factory = _make_pool()
    a = AuthValue(username="a", zone="iplant", password="pw")
    pool.get(a, host="other.example.org", port=1300)
    kwargs = factory.call_args.kwargs
    assert kwargs["host"] == "other.example.org"
    assert kwargs["port"] == 1300


def test_max_entries_must_be_positive():
    with pytest.raises(ValueError):
        IRODSClientPool(max_entries=0)


def test_factory_called_with_anonymous_scheme_for_anonymous_user():
    pool, factory = _make_pool()
    av = AuthValue(username="anonymous", zone="iplant", auth_scheme="anonymous")
    pool.get(av)
    kwargs = factory.call_args.kwargs
    assert kwargs["authentication_scheme"] == "anonymous"
    assert kwargs["password"] == ""
    assert kwargs["user"] == "anonymous"


def test_factory_called_with_native_scheme_and_password_for_native_user():
    pool, factory = _make_pool()
    av = AuthValue(username="alice", zone="iplant", password="hunter2")
    pool.get(av)
    kwargs = factory.call_args.kwargs
    assert kwargs["authentication_scheme"] == "native"
    assert kwargs["password"] == "hunter2"
    assert kwargs["user"] == "alice"
    assert kwargs["zone"] == "iplant"
