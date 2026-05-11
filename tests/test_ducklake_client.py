"""Tests for :mod:`mesa_mcp.ducklake.client`.

These cover the high-level :func:`record_avu_change` wrapper: silent
no-ops when DuckLake is disabled or the project isn't MESA-enabled, the
parent-walk project detection (cached), and the partial-failure path
that surfaces a :class:`DuckLakeMirrorError`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from mesa_mcp.auth import AuthValue
from mesa_mcp.ducklake import client as dl_client


@pytest.fixture
def alice() -> AuthValue:
    return AuthValue(username="alice", zone="iplant", password="hunter2")


@pytest.fixture(autouse=True)
def reset_singletons() -> Any:
    """Make sure every test starts with a clean cache + singleton."""
    dl_client.set_default_client(None)
    dl_client.reset_project_cache()
    yield
    dl_client.set_default_client(None)
    dl_client.reset_project_cache()


def _make_session_with_mesa_at(root: str) -> MagicMock:
    """Build a mock session whose ``metadata.get`` returns ``mesa.enabled=true``
    only for the given collection root.
    """
    session = MagicMock(name="iRODSSession")
    session.collections = MagicMock(name="collections")
    session.data_objects = MagicMock(name="data_objects")
    session.metadata = MagicMock(name="metadata")
    session.attributes = MagicMock(name="attributes")
    session.attributes.get.return_value = None

    def get_meta(model: Any, path: str) -> list[Any]:
        if path == root:
            m = MagicMock()
            m.name, m.value, m.units = "mesa.enabled", "true", ""
            return [m]
        return []

    session.metadata.get.side_effect = get_meta
    return session


async def test_no_client_is_silent_noop(alice: AuthValue) -> None:
    """When DuckLake singleton is None, record_avu_change just returns."""
    session = MagicMock(name="iRODSSession")
    dl_client.set_default_client(None)
    # No exception, no calls.
    await dl_client.record_avu_change(
        auth_value=alice,
        irods_path="/iplant/home/alice/file.csv",
        target_type="data_object",
        attribute="k",
        value="v",
        unit="",
        op="add",
        tool_name="ds_add_avu",
        session=session,
    )
    session.metadata.get.assert_not_called()


async def test_no_session_is_silent_noop(alice: AuthValue) -> None:
    """No session => can't detect project => silent no-op even with client set."""
    fake = MagicMock(name="DuckLakeClient")
    dl_client.set_default_client(fake)
    await dl_client.record_avu_change(
        auth_value=alice,
        irods_path="/iplant/home/alice/proj/file.csv",
        target_type="data_object",
        attribute="k",
        value="v",
        unit="",
        op="add",
        tool_name="ds_add_avu",
        session=None,
    )
    fake.find_project_by_path.assert_not_called()
    fake.record_changes.assert_not_called()


async def test_path_outside_mesa_project_is_silent_noop(alice: AuthValue) -> None:
    """Walk up parents; no parent has mesa.enabled => silent no-op."""
    session = MagicMock(name="iRODSSession")
    session.metadata = MagicMock(name="metadata")
    session.metadata.get.return_value = []
    fake = MagicMock(name="DuckLakeClient")
    dl_client.set_default_client(fake)

    await dl_client.record_avu_change(
        auth_value=alice,
        irods_path="/iplant/home/alice/file.csv",
        target_type="data_object",
        attribute="k",
        value="v",
        unit="",
        op="add",
        tool_name="ds_add_avu",
        session=session,
    )
    # We walked up looking for the AVU, but never called into the catalog.
    fake.find_project_by_path.assert_not_called()
    fake.record_changes.assert_not_called()


async def test_records_change_when_inside_mesa_project(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: parent has mesa.enabled=true and DuckLake mirror succeeds."""
    project_root = "/iplant/home/alice/proj"
    session = _make_session_with_mesa_at(project_root)

    project = MagicMock(project_id=UUID("00000000-0000-0000-0000-000000000001"))
    fake = MagicMock(name="DuckLakeClient")
    fake.find_project_by_path.return_value = project
    dl_client.set_default_client(fake)

    # Stub the AvuChange import path so we don't need mesa-ducklake installed.
    class _AvuChange:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    import sys
    import types

    fake_module = types.ModuleType("mesa_ducklake.models")
    fake_module.AvuChange = _AvuChange  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mesa_ducklake.models", fake_module)

    await dl_client.record_avu_change(
        auth_value=alice,
        irods_path=f"{project_root}/data/file.csv",
        target_type="data_object",
        attribute="envo.biome",
        value="forest",
        unit="ENVO:0001",
        op="add",
        tool_name="ds_add_avu",
        session=session,
    )

    fake.find_project_by_path.assert_called_once_with(project_root)
    fake.record_changes.assert_called_once()
    call_kwargs = fake.record_changes.call_args.kwargs
    assert call_kwargs["project_id"] == project.project_id
    assert call_kwargs["actor"] == "alice"
    [change] = call_kwargs["changes"]
    assert change.kwargs["attribute"] == "envo.biome"
    assert change.kwargs["irods_path"] == f"{project_root}/data/file.csv"
    assert change.kwargs["source"] == "mesa-mcp:ds_add_avu"


async def test_ducklake_write_failure_is_raised(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catalog write failures propagate as DuckLakeMirrorError."""
    project_root = "/iplant/home/alice/proj"
    session = _make_session_with_mesa_at(project_root)

    fake = MagicMock(name="DuckLakeClient")
    fake.find_project_by_path.return_value = MagicMock(project_id="proj-uuid")
    fake.record_changes.side_effect = RuntimeError("catalog unreachable")
    dl_client.set_default_client(fake)

    class _AvuChange:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    import sys
    import types

    fake_module = types.ModuleType("mesa_ducklake.models")
    fake_module.AvuChange = _AvuChange  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mesa_ducklake.models", fake_module)

    with pytest.raises(dl_client.DuckLakeMirrorError) as exc:
        await dl_client.record_avu_change(
            auth_value=alice,
            irods_path=f"{project_root}/file.csv",
            target_type="data_object",
            attribute="k",
            value="v",
            unit="",
            op="add",
            tool_name="ds_add_avu",
            session=session,
        )
    assert exc.value.project_id == "proj-uuid"


async def test_project_cache_short_circuits_repeat_walks(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After one positive detection, the next call must not re-query parents."""
    project_root = "/iplant/home/alice/proj"
    session = _make_session_with_mesa_at(project_root)

    fake = MagicMock(name="DuckLakeClient")
    fake.find_project_by_path.return_value = MagicMock(project_id="x")
    dl_client.set_default_client(fake)

    class _AvuChange:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    import sys
    import types

    fake_module = types.ModuleType("mesa_ducklake.models")
    fake_module.AvuChange = _AvuChange  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mesa_ducklake.models", fake_module)

    for _ in range(3):
        await dl_client.record_avu_change(
            auth_value=alice,
            irods_path=f"{project_root}/file{_}.csv",
            target_type="data_object",
            attribute="k",
            value=str(_),
            unit="",
            op="add",
            tool_name="ds_add_avu",
            session=session,
        )

    # Once a project root is cached as MESA-enabled, subsequent walks should
    # short-circuit at the cached ancestor instead of re-probing every parent
    # up to the zone root. So the metadata.get call count must stay bounded:
    # the first call walks file_path + project_root (2 probes), each later
    # call probes the new file_path then hits the cache (1 probe each).
    # Three total invocations -> at most 4 probes (2 + 1 + 1).
    assert session.metadata.get.call_count <= 4
