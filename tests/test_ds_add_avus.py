"""Tests for bulk AVU write: ``record_avu_changes`` and ``ds_add_avus``.

Test strategy mirrors tests/test_ds_avu_tools.py (pool/session mocking) and
tests/test_ducklake_client.py (DuckLake client injection via set_default_client).
All tests are offline/mocked — no network or iRODS required.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mesa_mcp.auth import AuthValue
from mesa_mcp.config import Config
from mesa_mcp.context import current_auth_value
from mesa_mcp.ducklake import client as dl_client
from mesa_mcp.ducklake.client import DuckLakeMirrorError, record_avu_changes
from mesa_mcp.errors import ToolError
from mesa_mcp.irods.client_pool import set_default_pool
from mesa_mcp.irods.tools import add_avus as add_avus_module
from mesa_mcp.server import MesaServer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def alice() -> AuthValue:
    return AuthValue(username="alice", zone="iplant", password="hunter2")


@pytest.fixture(autouse=True)
def reset_ducklake_singletons() -> Iterator[None]:
    """Ensure every test starts and ends with a clean DuckLake state."""
    dl_client.set_default_client(None)
    dl_client.reset_project_cache()
    yield
    dl_client.set_default_client(None)
    dl_client.reset_project_cache()


@pytest.fixture
def fake_avu_change_class(monkeypatch: pytest.MonkeyPatch) -> type:
    """Inject a fake ``mesa_ducklake.models`` module so AvuChange can be built."""

    class _AvuChange:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    fake_module = types.ModuleType("mesa_ducklake.models")
    fake_module.AvuChange = _AvuChange  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mesa_ducklake.models", fake_module)
    return _AvuChange


@pytest.fixture
def session() -> MagicMock:
    """A MagicMock that quacks like ``iRODSSession``."""
    s = MagicMock(name="iRODSSession")
    s.collections = MagicMock(name="collections")
    s.data_objects = MagicMock(name="data_objects")
    s.metadata = MagicMock(name="metadata")
    s.attributes = MagicMock(name="attributes")
    s.attributes.get.return_value = None
    return s


@pytest.fixture
def pool(session: MagicMock) -> Iterator[MagicMock]:
    """Install a fake pool whose ``get`` always returns ``session``."""
    fake = MagicMock(name="IRODSClientPool")
    fake.get.return_value = session
    set_default_pool(fake)
    try:
        yield fake
    finally:
        set_default_pool(None)


# ---------------------------------------------------------------------------
# record_avu_changes tests
# ---------------------------------------------------------------------------


async def test_record_avu_changes_batches_into_one_record_changes(
    alice: AuthValue,
    session: MagicMock,
    fake_avu_change_class: type,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three changes -> record_changes called EXACTLY ONCE with all three."""
    project_root = "/iplant/home/alice/proj"
    project = MagicMock(project_id="proj-uuid-batch")

    fake_client = MagicMock(name="DuckLakeClient")
    fake_client.find_project_by_path.return_value = project
    dl_client.set_default_client(fake_client)

    monkeypatch.setattr(dl_client, "_find_project_root", lambda *a, **kw: project_root)

    changes = [
        ("attr1", "val1", "unit1", "add"),
        ("attr2", "val2", "", "add"),
        ("attr3", "val3", "unit3", "add"),
    ]

    await record_avu_changes(
        auth_value=alice,
        irods_path=f"{project_root}/file.csv",
        target_type="data_object",
        changes=changes,
        tool_name="ds_add_avus",
        session=session,
    )

    # The key assertion: ONE call to record_changes, with all three changes.
    fake_client.record_changes.assert_called_once()
    call_kwargs = fake_client.record_changes.call_args.kwargs
    assert len(call_kwargs["changes"]) == 3


async def test_record_avu_changes_short_circuits_no_client(
    alice: AuthValue,
    session: MagicMock,
) -> None:
    """When DuckLake client is None, record_avu_changes is a silent no-op."""
    dl_client.set_default_client(None)

    # Should return None without raising.
    result = await record_avu_changes(
        auth_value=alice,
        irods_path="/iplant/home/alice/file.csv",
        target_type="data_object",
        changes=[("k", "v", "", "add")],
        tool_name="ds_add_avus",
        session=session,
    )
    assert result is None


async def test_record_avu_changes_short_circuits_no_session(
    alice: AuthValue,
) -> None:
    """When session is None, record_avu_changes is a silent no-op."""
    fake_client = MagicMock(name="DuckLakeClient")
    dl_client.set_default_client(fake_client)

    result = await record_avu_changes(
        auth_value=alice,
        irods_path="/iplant/home/alice/file.csv",
        target_type="data_object",
        changes=[("k", "v", "", "add")],
        tool_name="ds_add_avus",
        session=None,
    )
    assert result is None
    fake_client.record_changes.assert_not_called()


async def test_record_avu_changes_short_circuits_empty_changes(
    alice: AuthValue,
    session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty changes list -> no-op (no project lookup, no record_changes call)."""
    fake_client = MagicMock(name="DuckLakeClient")
    dl_client.set_default_client(fake_client)

    result = await record_avu_changes(
        auth_value=alice,
        irods_path="/iplant/home/alice/file.csv",
        target_type="data_object",
        changes=[],
        tool_name="ds_add_avus",
        session=session,
    )
    assert result is None
    fake_client.find_project_by_path.assert_not_called()
    fake_client.record_changes.assert_not_called()


async def test_record_avu_changes_short_circuits_no_project_root(
    alice: AuthValue,
    session: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When _find_project_root returns None, record_avu_changes is a no-op."""
    fake_client = MagicMock(name="DuckLakeClient")
    dl_client.set_default_client(fake_client)

    monkeypatch.setattr(dl_client, "_find_project_root", lambda *a, **kw: None)

    result = await record_avu_changes(
        auth_value=alice,
        irods_path="/iplant/home/alice/file.csv",
        target_type="data_object",
        changes=[("k", "v", "", "add")],
        tool_name="ds_add_avus",
        session=session,
    )
    assert result is None
    fake_client.record_changes.assert_not_called()


# ---------------------------------------------------------------------------
# ds_add_avus tool tests
# ---------------------------------------------------------------------------


async def test_ds_add_avus_writes_all_and_mirrors_once(
    alice: AuthValue,
    session: MagicMock,
    pool: MagicMock,
) -> None:
    """Three AVUs: add_avu_to_irods called 3 times, record_avu_changes awaited once."""
    server = MesaServer(config=Config())
    token = current_auth_value.set(alice)

    fake_avus = [
        {"attribute": "attr1", "value": "val1", "unit": "u1"},
        {"attribute": "attr2", "value": "val2", "unit": ""},
        {"attribute": "attr3", "value": "val3", "unit": "u3"},
    ]

    mock_record_changes = AsyncMock(return_value=None)

    def _fake_add_avu(session_arg: Any, path: str, target_type: Any, avu_dict: Any) -> dict:
        idx = int(avu_dict["attribute"][-1]) - 1  # attr1->0, attr2->1, attr3->2
        return fake_avus[idx]

    session.data_objects.get.return_value = MagicMock()

    try:
        with (
            patch.object(
                add_avus_module, "add_avu_to_irods", side_effect=_fake_add_avu
            ) as mock_add,
            patch.object(add_avus_module, "record_avu_changes", mock_record_changes),
        ):
            result = await server.call(
                "ds_add_avus",
                {
                    "target_type": "path",
                    "target": "/iplant/home/alice/file.csv",
                    "avus": [
                        {"attribute": "attr1", "value": "val1", "unit": "u1"},
                        {"attribute": "attr2", "value": "val2"},
                        {"attribute": "attr3", "value": "val3", "unit": "u3"},
                    ],
                },
            )
    finally:
        current_auth_value.reset(token)

    # add_avu_to_irods must be called once per AVU.
    assert mock_add.call_count == 3

    # record_avu_changes must be awaited exactly ONCE.
    mock_record_changes.assert_awaited_once()
    call_kwargs = mock_record_changes.call_args.kwargs
    assert len(call_kwargs["changes"]) == 3

    # Result shape.
    assert result["written"] == 3
    assert len(result["avus"]) == 3
    assert result["errors"] == []


async def test_ds_add_avus_continues_on_single_failure(
    alice: AuthValue,
    session: MagicMock,
    pool: MagicMock,
) -> None:
    """When add_avu_to_irods raises ToolError on 2nd of 3 AVUs:

    - other 2 are still written
    - 1 error is collected
    - record_avu_changes is called with the 2 successful changes
    """
    server = MesaServer(config=Config())
    token = current_auth_value.set(alice)

    call_count = 0

    def _flaky_add_avu(session_arg: Any, path: str, target_type: Any, avu_dict: Any) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise ToolError(code="irods_error", message="iCAT blew up on 2nd")
        return {"attribute": avu_dict["attribute"], "value": avu_dict["value"], "unit": ""}

    mock_record_changes = AsyncMock(return_value=None)
    session.data_objects.get.return_value = MagicMock()

    try:
        with (
            patch.object(add_avus_module, "add_avu_to_irods", side_effect=_flaky_add_avu),
            patch.object(add_avus_module, "record_avu_changes", mock_record_changes),
        ):
            result = await server.call(
                "ds_add_avus",
                {
                    "target_type": "path",
                    "target": "/iplant/home/alice/file.csv",
                    "avus": [
                        {"attribute": "k1", "value": "v1"},
                        {"attribute": "k2", "value": "v2"},
                        {"attribute": "k3", "value": "v3"},
                    ],
                },
            )
    finally:
        current_auth_value.reset(token)

    # 2 written, 1 error.
    assert result["written"] == 2
    assert len(result["errors"]) == 1
    assert result["errors"][0]["attribute"] == "k2"

    # record_avu_changes awaited ONCE with the 2 successful changes.
    mock_record_changes.assert_awaited_once()
    call_kwargs = mock_record_changes.call_args.kwargs
    assert len(call_kwargs["changes"]) == 2


async def test_ds_add_avus_unauthenticated_raises(
    session: MagicMock, pool: MagicMock
) -> None:
    """No auth_value -> ToolError unauthenticated (no auth_ctx fixture)."""
    server = MesaServer(config=Config())

    with pytest.raises(ToolError) as exc:
        await server.call(
            "ds_add_avus",
            {
                "target_type": "path",
                "target": "/iplant/home/alice/file.csv",
                "avus": [{"attribute": "k", "value": "v"}],
            },
        )
    assert exc.value.code == "unauthenticated"


async def test_ds_add_avus_ducklake_failure_returns_partial(
    alice: AuthValue,
    session: MagicMock,
    pool: MagicMock,
) -> None:
    """DuckLakeMirrorError -> partial_failure in result, iRODS writes intact."""
    server = MesaServer(config=Config())
    token = current_auth_value.set(alice)

    def _good_add(session_arg: Any, path: str, target_type: Any, avu_dict: Any) -> dict:
        return {"attribute": avu_dict["attribute"], "value": avu_dict["value"], "unit": ""}

    async def _failing_record(**kwargs: Any) -> None:
        raise DuckLakeMirrorError("catalog down", project_id="proj-xyz")

    session.data_objects.get.return_value = MagicMock()

    try:
        with (
            patch.object(add_avus_module, "add_avu_to_irods", side_effect=_good_add),
            patch.object(add_avus_module, "record_avu_changes", _failing_record),
        ):
            result = await server.call(
                "ds_add_avus",
                {
                    "target_type": "path",
                    "target": "/iplant/home/alice/file.csv",
                    "avus": [{"attribute": "k", "value": "v"}],
                },
            )
    finally:
        current_auth_value.reset(token)

    assert result["written"] == 1
    assert "partial_failure" in result
    assert result["partial_failure"]["code"] == "ducklake_mirror_failed"
    assert result["partial_failure"]["project_id"] == "proj-xyz"
