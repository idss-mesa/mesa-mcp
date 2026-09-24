"""``ds_use_ticket`` provenance must survive into later ``ds_add_avu`` calls.

Each MCP call runs in its own :mod:`contextvars` context, so the
``current_ticket`` contextvar set by ``ds_use_ticket`` is gone by the next
call. The durable binding is the caller's pooled session. These tests run
every tool call in its own task (``asyncio.create_task`` copies the
context, and sets inside it don't propagate back) to mirror that, and use a
real :class:`IRODSClientPool` so distinct identities get distinct sessions.
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.config import Config
from mesa_mcp.context import current_auth_value, current_ticket
from mesa_mcp.ducklake import client as dl_client
from mesa_mcp.irods.client_pool import IRODSClientPool, set_default_pool
from mesa_mcp.server import MesaServer


def _session_factory(**_kwargs: Any) -> MagicMock:
    """A fresh mock session per identity; ``mesa.enabled`` on each ``proj``."""
    session = MagicMock(name="iRODSSession")

    def get_meta(_model: Any, path: str) -> list[Any]:
        if path.endswith("/proj"):
            m = MagicMock()
            m.name, m.value, m.units = "mesa.enabled", "true", ""
            return [m]
        return []

    session.metadata.get.side_effect = get_meta
    return session


class _AvuChange:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


@pytest.fixture
def pool() -> Any:
    real = IRODSClientPool(config=Config(), session_factory=_session_factory)
    set_default_pool(real)
    yield real
    set_default_pool(None)


@pytest.fixture
def ducklake(monkeypatch: pytest.MonkeyPatch) -> Any:
    project = MagicMock(project_id=UUID("00000000-0000-0000-0000-000000000001"))
    fake = MagicMock(name="DuckLakeClient")
    fake.find_project_by_path.return_value = project
    dl_client.set_default_client(fake)
    dl_client.reset_project_cache()
    module = types.ModuleType("mesa_ducklake.models")
    module.AvuChange = _AvuChange  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mesa_ducklake.models", module)
    yield fake
    dl_client.set_default_client(None)
    dl_client.reset_project_cache()


async def _call(auth: AuthValue, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run one tool call in its own context, like a separate MCP request."""

    async def run() -> dict[str, Any]:
        current_auth_value.set(auth)
        return await MesaServer(config=Config()).call(tool, args)

    return await asyncio.create_task(run())


def _add_avu_args(user: str) -> dict[str, Any]:
    return {
        "target_type": "path",
        "target": f"/iplant/home/{user}/proj/file.csv",
        "attribute": "envo.biome",
        "value": "forest",
        "unit": "ENVO:0001",
    }


def _recorded_via_ticket(ducklake: MagicMock) -> Any:
    [change] = ducklake.record_changes.call_args.kwargs["changes"]
    return change.kwargs["via_ticket"]


async def test_use_ticket_then_add_avu_records_via_ticket(
    auth_value: AuthValue, pool: IRODSClientPool, ducklake: MagicMock
) -> None:
    await _call(auth_value, "ds_use_ticket", {"ticket": "TShared1"})
    # The ticket must not be reaching add_avu through this context.
    assert current_ticket.get() is None

    result = await _call(auth_value, "ds_add_avu", _add_avu_args("alice"))

    assert "partial_failure" not in result
    assert _recorded_via_ticket(ducklake) == "TShared1"
    # And Ticket.supply attached it to that same pooled session.
    assert pool.get(auth_value).ticket__ == "TShared1"


async def test_ticket_does_not_leak_to_another_identity(
    auth_value: AuthValue, pool: IRODSClientPool, ducklake: MagicMock
) -> None:
    bob = AuthValue(username="bob", zone="iplant", password="swordfish")
    await _call(auth_value, "ds_use_ticket", {"ticket": "TShared1"})

    await _call(bob, "ds_add_avu", _add_avu_args("bob"))

    assert _recorded_via_ticket(ducklake) is None
    assert pool.get(bob) is not pool.get(auth_value)
    assert pool.get(bob).ticket__ != "TShared1"


async def test_add_avu_without_ticket_records_none(
    auth_value: AuthValue, pool: IRODSClientPool, ducklake: MagicMock
) -> None:
    await _call(auth_value, "ds_add_avu", _add_avu_args("alice"))
    assert _recorded_via_ticket(ducklake) is None
