"""Shared pytest fixtures for the mesa-mcp test suite."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mesa_mcp.config import Config


@pytest.fixture
def config_fixture() -> Config:
    """A minimal :class:`Config` built from defaults — no network required."""
    return Config()


@pytest.fixture
def mock_irods_session() -> MagicMock:
    """A stand-in for ``iRODSSession`` so handler tests stay hermetic.

    The real session lives in ``python-irodsclient``. We expose ``collections``,
    ``data_objects``, ``metadata``, and ``query`` as :class:`MagicMock` so that
    tools ported from the Go reference (which uses ``go-irodsclient``) can
    assert on call shape without opening a TCP connection.
    """
    session = MagicMock(name="iRODSSession")
    session.collections = MagicMock(name="collections")
    session.data_objects = MagicMock(name="data_objects")
    session.metadata = MagicMock(name="metadata")
    session.query = MagicMock(name="query")
    return session
