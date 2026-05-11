"""Pytest fixtures for the ``ds_*`` iRODS tool tests.

The handlers read three pieces of state from
:mod:`mesa_mcp.context` (auth value, client pool, config). Tests want a
single ``with set_context(...)`` knob that:

1. Sets ``current_auth_value`` so :func:`require_current_auth_value`
   returns a known caller.
2. Sets ``current_client_pool`` so the handler can fetch a pre-built
   ``MagicMock`` session for the caller.
3. Sets ``current_config`` so WebDAV URL minting falls back to a known
   base URL.

We do this with a contextmanager so the contextvar reset is automatic on
exit — matching the way the production transport will set+reset around a
single MCP dispatch.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.config import Config
from mesa_mcp.context import (
    current_auth_value,
    current_client_pool,
    current_config,
)


@pytest.fixture
def auth_value() -> AuthValue:
    """A non-anonymous caller in the default ``iplant`` zone."""
    return AuthValue(username="alice", zone="iplant", password="hunter2")


@pytest.fixture
def anon_auth_value() -> AuthValue:
    """The iRODS ``anonymous`` pseudo-user. Used to assert write rejection."""
    return AuthValue(username="anonymous", zone="iplant", auth_scheme="anonymous")


@pytest.fixture
def config() -> Config:
    """Default config with a usable WebDAV base URL."""
    return Config()


@pytest.fixture
def mock_session() -> MagicMock:
    """A mock ``iRODSSession`` that quacks like the real thing.

    Each sub-namespace (``collections``, ``data_objects``, ``acls``,
    ``metadata``) is a :class:`MagicMock` whose return values tests can
    override per-case.
    """
    session = MagicMock(name="iRODSSession")
    session.collections = MagicMock(name="collections")
    session.data_objects = MagicMock(name="data_objects")
    session.acls = MagicMock(name="acls")
    session.metadata = MagicMock(name="metadata")
    session.query = MagicMock(name="query")
    return session


@pytest.fixture
def mock_pool(mock_session: MagicMock) -> MagicMock:
    """A pool whose ``get(auth_value)`` always hands back ``mock_session``."""
    pool = MagicMock(name="IRODSClientPool")
    pool.get = MagicMock(return_value=mock_session)
    return pool


@contextlib.contextmanager
def bind_context(
    *,
    auth_value: AuthValue | None,
    pool: Any | None,
    config: Config | None,
) -> Iterator[None]:
    """Temporarily set the three ``ds_*`` contextvars."""
    tokens = []
    if auth_value is not None:
        tokens.append(current_auth_value.set(auth_value))
    if pool is not None:
        tokens.append(current_client_pool.set(pool))
    if config is not None:
        tokens.append(current_config.set(config))
    try:
        yield
    finally:
        # Reset in reverse order — contextvar tokens must be popped LIFO.
        for tok in reversed(tokens):
            # Each contextvar carries its own token; we reset whichever var
            # the token references.
            tok.var.reset(tok)


@pytest.fixture
def context_binder():
    """Test-facing factory for binding context vars inside a ``with``-block."""
    return bind_context


def make_entry(
    path: str,
    *,
    kind: str = "data_object",
    size: int = 0,
    name: str | None = None,
) -> MagicMock:
    """Build a mock collection / data_object model with the given attributes."""
    mock = MagicMock()
    mock.path = path
    mock.name = name if name is not None else path.rsplit("/", 1)[-1] or "/"
    if kind == "data_object":
        mock.size = size
    return mock
