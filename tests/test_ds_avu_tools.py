"""Tests for the six AVU ``ds_*`` tools.

Each test drives the tool through :meth:`MesaServer.call`, which is the same
code path the MCP SDK adapter uses. ``iRODSSession`` is mocked, the iRODS
client pool's ``default_pool`` singleton is replaced, the AuthValue is
threaded in via ``mesa_mcp.context.current_auth_value``, and the DuckLake
``record_avu_change`` function is monkeypatched onto each tool module so we
can assert the wrapper is called without needing a real Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from mesa_mcp.auth import AuthValue
from mesa_mcp.config import Config
from mesa_mcp.context import current_auth_value
from mesa_mcp.ducklake.client import DuckLakeMirrorError
from mesa_mcp.errors import ToolError
from mesa_mcp.irods.client_pool import set_default_pool
from mesa_mcp.irods.tools import (
    add_avu,
    delete_avu,
    get_metadata,
    list_avus,
    search_files_by_avu,
    search_metadata,
)
from mesa_mcp.server import MesaServer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def alice() -> AuthValue:
    return AuthValue(username="alice", zone="iplant", password="hunter2")


@pytest.fixture
def server() -> MesaServer:
    return MesaServer(config=Config())


@pytest.fixture
def session() -> MagicMock:
    """A MagicMock that quacks like ``iRODSSession``."""
    s = MagicMock(name="iRODSSession")
    s.collections = MagicMock(name="collections")
    s.data_objects = MagicMock(name="data_objects")
    s.metadata = MagicMock(name="metadata")
    s.query = MagicMock(name="query")
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


@pytest.fixture
def auth_ctx(alice: AuthValue) -> Iterator[AuthValue]:
    """Bind ``alice`` to the request contextvar for the duration of the test."""
    token = current_auth_value.set(alice)
    try:
        yield alice
    finally:
        current_auth_value.reset(token)


@pytest.fixture
def recorded_changes(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace ``record_avu_change`` in each tool module with a recorder.

    Each invocation appends its kwargs to the returned list so tests can
    assert call shape without spinning up DuckLake / Postgres.
    """
    captured: list[dict[str, Any]] = []

    async def fake_record(**kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(add_avu, "record_avu_change", fake_record)
    monkeypatch.setattr(delete_avu, "record_avu_change", fake_record)
    return captured


@pytest.fixture
def mirror_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``record_avu_change`` with one that raises ``DuckLakeMirrorError``."""

    async def fake_record(**kwargs: Any) -> None:
        raise DuckLakeMirrorError("catalog unreachable", project_id="proj-uuid")

    monkeypatch.setattr(add_avu, "record_avu_change", fake_record)
    monkeypatch.setattr(delete_avu, "record_avu_change", fake_record)


# ---------------------------------------------------------------------------
# Registration sanity
# ---------------------------------------------------------------------------


class TestRegistration:
    @pytest.mark.parametrize(
        "tool_name",
        [
            "ds_list_avus",
            "ds_add_avu",
            "ds_delete_avu",
            "ds_search_files_by_avu",
            "ds_get_metadata",
            "ds_search_metadata",
        ],
    )
    def test_tool_is_registered(self, tool_name: str) -> None:
        from mesa_mcp.server import get_tool

        spec = get_tool(tool_name)
        assert spec.name == tool_name
        assert spec.input_model is not None


# ---------------------------------------------------------------------------
# ds_list_avus
# ---------------------------------------------------------------------------


class TestListAvus:
    async def test_happy_path(
        self,
        server: MesaServer,
        session: MagicMock,
        pool: MagicMock,
        auth_ctx: AuthValue,
    ) -> None:
        m = MagicMock()
        m.name, m.value, m.units, m.avu_id = "k", "v", "U", 11
        session.data_objects.get.return_value = MagicMock()
        session.metadata.get.return_value = [m]

        result = await server.call(
            "ds_list_avus",
            {"target_type": "path", "target": "/iplant/home/alice/file.csv"},
        )
        assert result["target"] == "/iplant/home/alice/file.csv"
        assert result["avus"] == [
            {"id": 11, "attribute": "k", "value": "v", "unit": "U"},
        ]
        assert result["path_target_type"] == "data_object"

    async def test_forbidden_path_raises(
        self, server: MesaServer, pool: MagicMock, auth_ctx: AuthValue
    ) -> None:
        with pytest.raises(ToolError) as exc:
            await server.call(
                "ds_list_avus",
                {"target_type": "path", "target": "/iplant/home/bob/file.csv"},
            )
        assert exc.value.code == "forbidden"


# ---------------------------------------------------------------------------
# ds_add_avu
# ---------------------------------------------------------------------------


class TestAddAvu:
    async def test_writes_and_records_change(
        self,
        server: MesaServer,
        session: MagicMock,
        pool: MagicMock,
        auth_ctx: AuthValue,
        recorded_changes: list[dict[str, Any]],
    ) -> None:
        session.data_objects.get.return_value = MagicMock()
        result = await server.call(
            "ds_add_avu",
            {
                "target_type": "path",
                "target": "/iplant/home/alice/file.csv",
                "attribute": "envo.biome",
                "value": "forest",
                "unit": "ENVO:0001",
            },
        )
        assert result["avu"] == {
            "attribute": "envo.biome",
            "value": "forest",
            "unit": "ENVO:0001",
        }
        # Underlying iRODS call happened.
        session.metadata.add.assert_called_once()
        # DuckLake wrapper called once with the expected shape.
        assert len(recorded_changes) == 1
        call = recorded_changes[0]
        assert call["irods_path"] == "/iplant/home/alice/file.csv"
        assert call["target_type"] == "data_object"
        assert call["op"] == "add"
        assert call["tool_name"] == "ds_add_avu"
        assert call["auth_value"].username == "alice"
        assert call["attribute"] == "envo.biome"

    async def test_forbidden_path_raises(
        self, server: MesaServer, pool: MagicMock, auth_ctx: AuthValue
    ) -> None:
        with pytest.raises(ToolError) as exc:
            await server.call(
                "ds_add_avu",
                {
                    "target_type": "path",
                    "target": "/iplant/home/bob/file.csv",
                    "attribute": "k",
                    "value": "v",
                },
            )
        assert exc.value.code == "forbidden"

    async def test_irods_failure_surfaces(
        self,
        server: MesaServer,
        session: MagicMock,
        pool: MagicMock,
        auth_ctx: AuthValue,
        recorded_changes: list[dict[str, Any]],
    ) -> None:
        session.data_objects.get.return_value = MagicMock()
        session.metadata.add.side_effect = RuntimeError("iCAT down")
        with pytest.raises(ToolError) as exc:
            await server.call(
                "ds_add_avu",
                {
                    "target_type": "path",
                    "target": "/iplant/home/alice/file.csv",
                    "attribute": "k",
                    "value": "v",
                },
            )
        assert exc.value.code == "irods_error"
        # No DuckLake call because the iRODS write failed.
        assert recorded_changes == []

    async def test_ducklake_failure_returns_partial(
        self,
        server: MesaServer,
        session: MagicMock,
        pool: MagicMock,
        auth_ctx: AuthValue,
        mirror_fails: None,
    ) -> None:
        session.data_objects.get.return_value = MagicMock()
        result = await server.call(
            "ds_add_avu",
            {
                "target_type": "path",
                "target": "/iplant/home/alice/file.csv",
                "attribute": "k",
                "value": "v",
            },
        )
        # iRODS write still reflected in the result.
        session.metadata.add.assert_called_once()
        assert result["avu"]["attribute"] == "k"
        # Partial failure surfaced with a stable code.
        assert "partial_failure" in result
        assert result["partial_failure"]["code"] == "ducklake_mirror_failed"


# ---------------------------------------------------------------------------
# ds_delete_avu
# ---------------------------------------------------------------------------


class TestDeleteAvu:
    async def test_deletes_and_records_change(
        self,
        server: MesaServer,
        session: MagicMock,
        pool: MagicMock,
        auth_ctx: AuthValue,
        recorded_changes: list[dict[str, Any]],
    ) -> None:
        session.data_objects.get.return_value = MagicMock()
        result = await server.call(
            "ds_delete_avu",
            {
                "target_type": "path",
                "target": "/iplant/home/alice/file.csv",
                "attribute": "k",
                "value": "v",
                "unit": "U",
            },
        )
        assert result["attribute"] == "k"
        session.metadata.remove.assert_called_once()
        assert len(recorded_changes) == 1
        assert recorded_changes[0]["op"] == "delete"
        assert recorded_changes[0]["tool_name"] == "ds_delete_avu"

    async def test_forbidden_path_raises(
        self, server: MesaServer, pool: MagicMock, auth_ctx: AuthValue
    ) -> None:
        with pytest.raises(ToolError) as exc:
            await server.call(
                "ds_delete_avu",
                {
                    "target_type": "path",
                    "target": "/iplant/home/bob/file.csv",
                    "attribute": "k",
                },
            )
        assert exc.value.code == "forbidden"

    async def test_ducklake_failure_returns_partial(
        self,
        server: MesaServer,
        session: MagicMock,
        pool: MagicMock,
        auth_ctx: AuthValue,
        mirror_fails: None,
    ) -> None:
        session.data_objects.get.return_value = MagicMock()
        result = await server.call(
            "ds_delete_avu",
            {
                "target_type": "path",
                "target": "/iplant/home/alice/file.csv",
                "attribute": "k",
                "value": "v",
            },
        )
        assert "partial_failure" in result
        assert result["partial_failure"]["code"] == "ducklake_mirror_failed"


# ---------------------------------------------------------------------------
# ds_search_files_by_avu
# ---------------------------------------------------------------------------


class TestSearchFilesByAvu:
    async def test_filters_to_accessible_paths(
        self,
        server: MesaServer,
        session: MagicMock,
        pool: MagicMock,
        auth_ctx: AuthValue,
    ) -> None:
        # Build two synthetic rows: one inside alice's home, one in bob's.
        def make_data_row(coll: str, name: str) -> Any:
            from irods.models import Collection, DataObject

            return {Collection.name: coll, DataObject.name: name}

        first_query = MagicMock()
        first_query.filter.return_value = first_query
        first_query.all.return_value = [
            make_data_row("/iplant/home/alice", "file.csv"),
            make_data_row("/iplant/home/bob", "secret.csv"),
        ]
        # Empty collection query.
        second_query = MagicMock()
        second_query.filter.return_value = second_query
        second_query.all.return_value = []

        session.query.side_effect = [first_query, second_query]

        result = await server.call(
            "ds_search_files_by_avu", {"attribute": "k", "value": "v"}
        )
        assert {e["path"] for e in result["matching_entries"]} == {
            "/iplant/home/alice/file.csv",
        }

    async def test_unauthenticated_raises(self, server: MesaServer) -> None:
        # No auth_ctx fixture — contextvar is None.
        with pytest.raises(ToolError) as exc:
            await server.call(
                "ds_search_files_by_avu", {"attribute": "k", "value": "v"}
            )
        assert exc.value.code == "unauthenticated"


# ---------------------------------------------------------------------------
# ds_get_metadata
# ---------------------------------------------------------------------------


class TestGetMetadata:
    async def test_happy_path(
        self,
        server: MesaServer,
        session: MagicMock,
        pool: MagicMock,
        auth_ctx: AuthValue,
    ) -> None:
        session.data_objects.get.return_value = MagicMock()
        m = MagicMock()
        m.name, m.value, m.units, m.avu_id = "k", "v", "U", 1
        session.metadata.get.return_value = [m]
        result = await server.call(
            "ds_get_metadata", {"path": "/iplant/home/alice/file.csv"}
        )
        assert result["path"] == "/iplant/home/alice/file.csv"
        assert result["target_type"] == "data_object"
        assert result["avus"][0]["attribute"] == "k"

    async def test_forbidden(
        self, server: MesaServer, pool: MagicMock, auth_ctx: AuthValue
    ) -> None:
        with pytest.raises(ToolError) as exc:
            await server.call(
                "ds_get_metadata", {"path": "/iplant/home/bob/file.csv"}
            )
        assert exc.value.code == "forbidden"


# ---------------------------------------------------------------------------
# ds_search_metadata
# ---------------------------------------------------------------------------


class TestSearchMetadata:
    async def test_at_least_one_predicate_required(
        self, server: MesaServer, pool: MagicMock, auth_ctx: AuthValue
    ) -> None:
        with pytest.raises(ToolError) as exc:
            await server.call("ds_search_metadata", {})
        # Pydantic validation rolls up as invalid_argument from _invoke_handler.
        assert exc.value.code == "invalid_argument"

    async def test_returns_filtered_entries(
        self,
        server: MesaServer,
        session: MagicMock,
        pool: MagicMock,
        auth_ctx: AuthValue,
    ) -> None:
        from irods.models import Collection, DataObject

        data_q = MagicMock()
        data_q.filter.return_value = data_q
        data_q.all.return_value = [
            {Collection.name: "/iplant/home/alice", DataObject.name: "x.csv"},
        ]
        coll_q = MagicMock()
        coll_q.filter.return_value = coll_q
        coll_q.all.return_value = [
            {Collection.name: "/iplant/home/alice/data"},
        ]
        session.query.side_effect = [data_q, coll_q]

        result = await server.call("ds_search_metadata", {"attribute": "k"})
        paths = {e["path"] for e in result["matching_entries"]}
        assert paths == {"/iplant/home/alice/x.csv", "/iplant/home/alice/data"}

    async def test_irods_failure_surfaces(
        self,
        server: MesaServer,
        session: MagicMock,
        pool: MagicMock,
        auth_ctx: AuthValue,
    ) -> None:
        q = MagicMock()
        q.filter.return_value = q
        q.all.side_effect = RuntimeError("iCAT timeout")
        session.query.return_value = q

        with pytest.raises(ToolError) as exc:
            await server.call("ds_search_metadata", {"attribute": "k"})
        assert exc.value.code == "irods_error"


# ---------------------------------------------------------------------------
# Unused-import keep-alive: pytest will gripe if we import a module only
# to monkeypatch it. The fixture above patches via attribute access so the
# explicit references in the imports list must be visible at module load.
# ---------------------------------------------------------------------------

_KEEP = (list_avus, get_metadata, search_files_by_avu, search_metadata)
