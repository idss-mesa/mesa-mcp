"""Tests for the composite ``mesa_avu_apply_term`` tool.

The tool stitches together: path-access validation, an OLS term lookup
(skippable when ``label`` + ``curie`` are inline), the canonical AVU
transform, the iRODS add helper, and the DuckLake mirror. Each test
exercises one of those seams.
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
from mesa_mcp.ols import set_default_client
from mesa_mcp.ols.tools import avu_apply_term
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
    s = MagicMock(name="iRODSSession")
    s.collections = MagicMock(name="collections")
    s.data_objects = MagicMock(name="data_objects")
    s.metadata = MagicMock(name="metadata")
    s.query = MagicMock(name="query")
    s.attributes = MagicMock(name="attributes")
    s.attributes.get.return_value = None
    s.data_objects.get.return_value = MagicMock()
    return s


@pytest.fixture
def pool(session: MagicMock) -> Iterator[MagicMock]:
    fake = MagicMock(name="IRODSClientPool")
    fake.get.return_value = session
    set_default_pool(fake)
    try:
        yield fake
    finally:
        set_default_pool(None)


@pytest.fixture
def auth_ctx(alice: AuthValue) -> Iterator[AuthValue]:
    token = current_auth_value.set(alice)
    try:
        yield alice
    finally:
        current_auth_value.reset(token)


@pytest.fixture
def fake_ols() -> Iterator[MagicMock]:
    """Install a mock OLSClient as the module-level singleton."""
    client = MagicMock(name="OLSClient")
    set_default_client(client)
    try:
        yield client
    finally:
        set_default_client(None)


@pytest.fixture
def recorded_changes(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    async def fake_record(**kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(avu_apply_term, "record_avu_change", fake_record)
    return captured


@pytest.fixture
def mirror_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_record(**kwargs: Any) -> None:
        raise DuckLakeMirrorError("postgres unreachable", project_id="proj-uuid")

    monkeypatch.setattr(avu_apply_term, "record_avu_change", fake_record)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestApplyTermHappyPath:
    async def test_term_lookup_avu_write_and_ducklake_record(
        self,
        server: MesaServer,
        session: MagicMock,
        pool: MagicMock,
        auth_ctx: AuthValue,
        fake_ols: MagicMock,
        recorded_changes: list[dict[str, Any]],
    ) -> None:
        fake_ols.get_term.return_value = {
            "label": "biome",
            "iri": "http://purl.obolibrary.org/obo/ENVO_00000428",
            "curie": "ENVO:00000428",
        }
        result = await server.call(
            "mesa_avu_apply_term",
            {
                "path": "/iplant/home/alice/file.csv",
                "ontology_id": "envo",
                "value": "tropical forest",
                "iri": "http://purl.obolibrary.org/obo/ENVO_00000428",
            },
        )

        # AVU written to iRODS.
        session.metadata.add.assert_called_once()

        assert result["avu"] == {
            "attribute": "envo.biome",
            "value": "tropical forest",
            "unit": "ENVO:00000428",
        }
        assert result["term"]["label"] == "biome"
        assert result["term"]["curie"] == "ENVO:00000428"

        # DuckLake mirror was called with matching shape.
        assert len(recorded_changes) == 1
        rec = recorded_changes[0]
        assert rec["irods_path"] == "/iplant/home/alice/file.csv"
        assert rec["attribute"] == "envo.biome"
        assert rec["op"] == "add"
        assert rec["tool_name"] == "mesa_avu_apply_term"

    async def test_inline_label_skips_ols_lookup(
        self,
        server: MesaServer,
        session: MagicMock,
        pool: MagicMock,
        auth_ctx: AuthValue,
        fake_ols: MagicMock,
        recorded_changes: list[dict[str, Any]],
    ) -> None:
        result = await server.call(
            "mesa_avu_apply_term",
            {
                "path": "/iplant/home/alice/file.csv",
                "ontology_id": "envo",
                "value": "forest",
                "label": "Environmental Feature",
                "curie": "ENVO:00002297",
            },
        )
        fake_ols.get_term.assert_not_called()
        assert result["avu"]["attribute"] == "envo.environmental_feature"
        assert result["avu"]["unit"] == "ENVO:00002297"


class TestApplyTermErrorPaths:
    async def test_forbidden_path_raises(
        self,
        server: MesaServer,
        pool: MagicMock,
        auth_ctx: AuthValue,
        fake_ols: MagicMock,
        recorded_changes: list[dict[str, Any]],
    ) -> None:
        with pytest.raises(ToolError) as exc:
            await server.call(
                "mesa_avu_apply_term",
                {
                    "path": "/iplant/home/bob/file.csv",
                    "ontology_id": "envo",
                    "value": "x",
                    "curie": "ENVO:00000001",
                    "label": "biome",
                },
            )
        assert exc.value.code == "forbidden"
        # Never reached iRODS or DuckLake.
        fake_ols.get_term.assert_not_called()
        assert recorded_changes == []

    async def test_unknown_term_raises(
        self,
        server: MesaServer,
        session: MagicMock,
        pool: MagicMock,
        auth_ctx: AuthValue,
        fake_ols: MagicMock,
        recorded_changes: list[dict[str, Any]],
    ) -> None:
        fake_ols.get_term.return_value = None
        with pytest.raises(ToolError) as exc:
            await server.call(
                "mesa_avu_apply_term",
                {
                    "path": "/iplant/home/alice/file.csv",
                    "ontology_id": "envo",
                    "value": "x",
                    "iri": "http://example.com/missing",
                },
            )
        assert exc.value.code == "not_found"
        # iRODS metadata.add should NOT have been called.
        session.metadata.add.assert_not_called()
        assert recorded_changes == []

    async def test_missing_iri_and_curie_raises(
        self,
        server: MesaServer,
        pool: MagicMock,
        auth_ctx: AuthValue,
        fake_ols: MagicMock,
    ) -> None:
        with pytest.raises(ToolError) as exc:
            await server.call(
                "mesa_avu_apply_term",
                {
                    "path": "/iplant/home/alice/file.csv",
                    "ontology_id": "envo",
                    "value": "x",
                },
            )
        assert exc.value.code == "invalid_argument"

    async def test_ducklake_unreachable_returns_partial(
        self,
        server: MesaServer,
        session: MagicMock,
        pool: MagicMock,
        auth_ctx: AuthValue,
        fake_ols: MagicMock,
        mirror_fails: None,
    ) -> None:
        result = await server.call(
            "mesa_avu_apply_term",
            {
                "path": "/iplant/home/alice/file.csv",
                "ontology_id": "envo",
                "value": "x",
                "curie": "ENVO:0001",
                "label": "biome",
            },
        )
        # iRODS state intact.
        session.metadata.add.assert_called_once()
        # Partial failure surfaced with the documented code.
        assert "partial_failure" in result
        assert result["partial_failure"]["code"] == "ducklake_mirror_failed"
        assert result["avu"]["attribute"] == "envo.biome"

    async def test_unauthenticated_raises(self, server: MesaServer) -> None:
        # No auth_ctx fixture — contextvar default is None.
        with pytest.raises(ToolError) as exc:
            await server.call(
                "mesa_avu_apply_term",
                {
                    "path": "/iplant/home/alice/file.csv",
                    "ontology_id": "envo",
                    "value": "x",
                    "curie": "ENVO:0001",
                    "label": "biome",
                },
            )
        assert exc.value.code == "unauthenticated"
