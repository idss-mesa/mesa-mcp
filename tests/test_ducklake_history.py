"""Tests for the ``mesa_ducklake_history`` MCP tool.

Same approach as ``tests/test_ducklake_init_project.py``: the handler is
called directly, iRODS is a ``MagicMock`` session, and the DuckLake
client is a fake injected with ``set_default_client``. Nothing here needs
a network, an iRODS server, or the ``mesa-ducklake`` package.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from mesa_mcp.auth import AuthValue
from mesa_mcp.ducklake import client as dl_client
from mesa_mcp.ducklake.tools import history as history_module
from mesa_mcp.ducklake.tools.history import (
    MAX_LIMIT,
    HistoryInput,
    handle_mesa_ducklake_history,
)
from mesa_mcp.errors import ToolError

PROJECT_ROOT = "/iplant/home/alice/proj"
FILE_PATH = f"{PROJECT_ROOT}/data/sample.csv"


@pytest.fixture
def alice() -> AuthValue:
    return AuthValue(username="alice", zone="iplant", password="hunter2")


@pytest.fixture(autouse=True)
def reset_singletons() -> Any:
    """Clean DuckLake singleton and project-detection cache around every test."""
    dl_client.set_default_client(None)
    dl_client.reset_project_cache()
    yield
    dl_client.set_default_client(None)
    dl_client.reset_project_cache()


class FakeAvuChange(BaseModel):
    """Stand-in for ``mesa_ducklake.models.AvuChange`` with the same fields."""

    project_id: UUID | None = None
    snapshot_id: int | None = None
    irods_path: str = FILE_PATH
    target_type: str = "data_object"
    attribute: str = "k"
    value: str = "v"
    unit: str = ""
    op: str = "add"
    actor: str = "alice"
    ts: datetime = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    source: str = "mesa-mcp"
    via_ticket: str | None = None
    rule_invocation: str | None = None


def _fake_session(mesa_root: str | None = PROJECT_ROOT) -> MagicMock:
    """Session whose ``metadata.get`` reports ``mesa.enabled=true`` only on ``mesa_root``."""
    session = MagicMock(name="iRODSSession")
    session.collections = MagicMock(name="collections")
    session.metadata = MagicMock(name="metadata")

    def get_meta(model: Any, path: str) -> list[Any]:
        if mesa_root is not None and path == mesa_root:
            m = MagicMock()
            m.name, m.value, m.units = "mesa.enabled", "true", ""
            return [m]
        return []

    session.metadata.get.side_effect = get_meta
    return session


def _patch_access_and_pool(monkeypatch: pytest.MonkeyPatch, session: MagicMock) -> None:
    """Make assert_allowed pass-through and default_pool yield the mock session.

    Patches the names *as imported into history.py*.
    """
    monkeypatch.setattr(history_module, "assert_allowed", lambda path, av: path)  # noqa: ARG005
    fake_pool = MagicMock(name="pool")
    fake_pool.get.return_value = session
    monkeypatch.setattr(history_module, "default_pool", lambda: fake_pool)


def _fake_project(irods_path: str = PROJECT_ROOT) -> Any:
    proj = MagicMock(name="Project")
    proj.project_id = uuid4()
    proj.irods_path = irods_path
    return proj


def _fake_client(
    *,
    project: Any | None,
    history_rows: list[FakeAvuChange] | None = None,
    as_of_rows: list[FakeAvuChange] | None = None,
) -> MagicMock:
    client = MagicMock(name="DuckLakeClient")
    client.find_project_by_path.return_value = project
    client.get_history.return_value = history_rows or []
    client.get_avus_as_of.return_value = as_of_rows or []
    return client


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------


def test_history_tool_is_registered() -> None:
    from mesa_mcp.server import get_tool

    assert get_tool("mesa_ducklake_history").handler is handle_mesa_ducklake_history


async def test_history_requires_auth() -> None:
    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_history(HistoryInput(irods_path=FILE_PATH), auth_value=None)
    assert exc_info.value.code == "unauthenticated"


async def test_history_errors_when_ducklake_disabled(alice: AuthValue) -> None:
    dl_client.set_default_client(None)

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_history(HistoryInput(irods_path=FILE_PATH), auth_value=alice)
    assert exc_info.value.code == "ducklake_disabled"


async def test_history_errors_when_path_not_in_project(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ancestor carries mesa.enabled=true => not_mesa_project, no catalog call."""
    session = _fake_session(mesa_root=None)
    _patch_access_and_pool(monkeypatch, session)
    client = _fake_client(project=_fake_project())
    dl_client.set_default_client(client)

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_history(HistoryInput(irods_path=FILE_PATH), auth_value=alice)
    assert exc_info.value.code == "not_mesa_project"
    client.find_project_by_path.assert_not_called()
    client.get_history.assert_not_called()


async def test_history_errors_when_project_not_registered(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AVU present but no catalog row => drift, surfaced as its own code."""
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    client = _fake_client(project=None)
    dl_client.set_default_client(client)

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_history(HistoryInput(irods_path=FILE_PATH), auth_value=alice)
    assert exc_info.value.code == "history_project_not_registered"
    client.find_project_by_path.assert_called_once_with(PROJECT_ROOT)
    client.get_history.assert_not_called()


async def test_history_errors_when_catalog_lookup_fails(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    client = _fake_client(project=None)
    client.find_project_by_path.side_effect = RuntimeError("postgres down")
    dl_client.set_default_client(client)

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_history(HistoryInput(irods_path=FILE_PATH), auth_value=alice)
    assert exc_info.value.code == "history_failed_catalog_lookup"


async def test_history_errors_when_read_fails(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    client = _fake_client(project=_fake_project())
    client.get_history.side_effect = RuntimeError("parquet missing")
    dl_client.set_default_client(client)

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_history(HistoryInput(irods_path=FILE_PATH), auth_value=alice)
    assert exc_info.value.code == "history_failed_read"


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_history_returns_change_log(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    project = _fake_project()
    rows = [
        FakeAvuChange(snapshot_id=2, attribute="b", value="2", op="delete"),
        FakeAvuChange(snapshot_id=1, attribute="a", value="1"),
    ]
    client = _fake_client(project=project, history_rows=rows)
    dl_client.set_default_client(client)

    result = await handle_mesa_ducklake_history(
        HistoryInput(irods_path=FILE_PATH), auth_value=alice
    )

    # The library is asked for the full scan window; the session is passed
    # so it can pull Parquet from iRODS into its cache.
    client.get_history.assert_called_once_with(
        project.project_id, FILE_PATH, limit=MAX_LIMIT, session=session
    )
    client.get_avus_as_of.assert_not_called()

    assert result["project_id"] == str(project.project_id)
    assert result["count"] == 2
    # Rows are JSON-mode dumps: datetimes become strings, order is preserved.
    assert [r["snapshot_id"] for r in result["rows"]] == [2, 1]
    assert result["rows"][0]["op"] == "delete"
    assert result["rows"][0]["ts"] == "2026-09-01T12:00:00Z"
    assert set(result["rows"][0]) == set(FakeAvuChange.model_fields)


async def test_history_as_of_returns_effective_avus(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    project = _fake_project()
    client = _fake_client(project=project, as_of_rows=[FakeAvuChange(attribute="a")])
    dl_client.set_default_client(client)

    result = await handle_mesa_ducklake_history(
        HistoryInput(irods_path=FILE_PATH, as_of="2026-09-01T12:00:00Z"), auth_value=alice
    )

    client.get_avus_as_of.assert_called_once_with(
        project.project_id,
        FILE_PATH,
        datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        session=session,
    )
    client.get_history.assert_not_called()
    assert result["count"] == 1
    assert result["rows"][0]["attribute"] == "a"


@pytest.mark.parametrize(
    "as_of",
    [
        "2026-09-01T12:00:00Z",  # Z suffix
        "2026-09-01T12:00:00+00:00",  # explicit UTC
        "2026-09-01T14:00:00+02:00",  # other zone, same instant
        "2026-09-01T12:00:00",  # naive => UTC
        "  2026-09-01T12:00:00Z  ",  # surrounding whitespace
    ],
)
def test_parse_as_of_normalizes_to_utc(as_of: str) -> None:
    assert history_module._parse_as_of(as_of) == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_parse_as_of_none_passes_through() -> None:
    assert history_module._parse_as_of(None) is None


async def test_history_rejects_malformed_as_of(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad timestamp fails before any iRODS or catalog call."""
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    client = _fake_client(project=_fake_project())
    dl_client.set_default_client(client)

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_history(
            HistoryInput(irods_path=FILE_PATH, as_of="last tuesday"), auth_value=alice
        )
    assert exc_info.value.code == "invalid_argument"
    session.metadata.get.assert_not_called()
    client.find_project_by_path.assert_not_called()


async def test_history_filters_by_attribute(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    rows = [
        FakeAvuChange(attribute="envo.biome", value="x"),
        FakeAvuChange(attribute="other", value="y"),
        FakeAvuChange(attribute="envo.biome", value="z"),
        FakeAvuChange(attribute="envo.biomes", value="prefix-only"),
    ]
    client = _fake_client(project=_fake_project(), history_rows=rows)
    dl_client.set_default_client(client)

    result = await handle_mesa_ducklake_history(
        HistoryInput(irods_path=FILE_PATH, attribute="envo.biome"), auth_value=alice
    )

    assert result["count"] == 2
    assert [r["value"] for r in result["rows"]] == ["x", "z"]


async def test_history_filters_by_unit(alice: AuthValue, monkeypatch: pytest.MonkeyPatch) -> None:
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    rows = [
        FakeAvuChange(value="curie", unit="ENVO:01000174"),
        FakeAvuChange(value="bare", unit=""),
        FakeAvuChange(value="other-curie", unit="ENVO:00000446"),
    ]
    client = _fake_client(project=_fake_project(), history_rows=rows)
    dl_client.set_default_client(client)

    result = await handle_mesa_ducklake_history(
        HistoryInput(irods_path=FILE_PATH, unit="ENVO:01000174"), auth_value=alice
    )
    assert [r["value"] for r in result["rows"]] == ["curie"]

    # Empty string is a real filter (rows with no unit), not "no filter".
    result = await handle_mesa_ducklake_history(
        HistoryInput(irods_path=FILE_PATH, unit=""), auth_value=alice
    )
    assert [r["value"] for r in result["rows"]] == ["bare"]


async def test_history_filters_apply_to_as_of_rows_too(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    rows = [FakeAvuChange(attribute="a", unit="u1"), FakeAvuChange(attribute="a", unit="u2")]
    client = _fake_client(project=_fake_project(), as_of_rows=rows)
    dl_client.set_default_client(client)

    result = await handle_mesa_ducklake_history(
        HistoryInput(irods_path=FILE_PATH, as_of="2026-09-01T00:00:00Z", attribute="a", unit="u2"),
        auth_value=alice,
    )
    assert result["count"] == 1
    assert result["rows"][0]["unit"] == "u2"


# ---------------------------------------------------------------------------
# Limit handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(100, 100), (1, 1), (0, 1), (-5, 1), (1000, 1000), (1001, 1000), (5000, 1000)],
)
def test_clamp_limit(requested: int, expected: int) -> None:
    assert history_module._clamp_limit(requested) == expected


async def test_history_limit_is_capped(alice: AuthValue, monkeypatch: pytest.MonkeyPatch) -> None:
    """limit=5000 => library asked for MAX_LIMIT, and at most MAX_LIMIT rows returned."""
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    rows = [FakeAvuChange(snapshot_id=i) for i in range(MAX_LIMIT + 200)]
    client = _fake_client(project=_fake_project(), history_rows=rows)
    dl_client.set_default_client(client)

    result = await handle_mesa_ducklake_history(
        HistoryInput(irods_path=FILE_PATH, limit=5000), auth_value=alice
    )

    assert client.get_history.call_args.kwargs["limit"] == MAX_LIMIT
    assert result["count"] == MAX_LIMIT
    assert len(result["rows"]) == MAX_LIMIT


async def test_history_limit_truncates_after_filtering(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A small limit with a filter returns `limit` *matching* rows, not `limit` scanned rows."""
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    rows = [
        FakeAvuChange(attribute="other", value="0"),
        FakeAvuChange(attribute="other", value="1"),
        FakeAvuChange(attribute="want", value="2"),
        FakeAvuChange(attribute="want", value="3"),
        FakeAvuChange(attribute="want", value="4"),
    ]
    client = _fake_client(project=_fake_project(), history_rows=rows)
    dl_client.set_default_client(client)

    result = await handle_mesa_ducklake_history(
        HistoryInput(irods_path=FILE_PATH, attribute="want", limit=2), auth_value=alice
    )

    client.get_history.assert_called_once()
    assert client.get_history.call_args.kwargs["limit"] == MAX_LIMIT
    assert [r["value"] for r in result["rows"]] == ["2", "3"]
    assert result["count"] == 2


async def test_history_resolves_project_from_nested_path(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The catalog lookup uses the *project root*, not the queried path."""
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    client = _fake_client(project=_fake_project())
    dl_client.set_default_client(client)

    nested = f"{PROJECT_ROOT}/a/b/c/deep.txt"
    await handle_mesa_ducklake_history(HistoryInput(irods_path=nested), auth_value=alice)

    client.find_project_by_path.assert_called_once_with(PROJECT_ROOT)
    # ...but the history read is for the queried path itself.
    assert client.get_history.call_args.args[1] == nested
