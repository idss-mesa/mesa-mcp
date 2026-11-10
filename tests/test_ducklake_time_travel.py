"""Tests for the ``mesa_ducklake_time_travel`` MCP tool.

Same approach as ``tests/test_ducklake_init_project.py``: the handler is
called directly, iRODS is a ``MagicMock`` session, and the DuckLake
client is a fake injected with ``set_default_client``. Nothing here needs
a network, an iRODS server, or the ``mesa-ducklake`` package.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from mesa_mcp.auth import AuthValue
from mesa_mcp.ducklake import client as dl_client
from mesa_mcp.ducklake.tools import time_travel as tt_module
from mesa_mcp.ducklake.tools.time_travel import (
    MAX_LIMIT,
    TimeTravelInput,
    handle_mesa_ducklake_time_travel,
)
from mesa_mcp.errors import ToolError

PROJECT_ROOT = "/iplant/home/alice/proj"
FILE_PATH = f"{PROJECT_ROOT}/data/sample.csv"
AS_OF = "2026-09-01T12:00:00Z"
AS_OF_DT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


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
    ts: datetime = datetime(2026, 9, 1, 11, 0, tzinfo=UTC)
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

    Patches the names *as imported into time_travel.py*.
    """
    monkeypatch.setattr(tt_module, "assert_allowed", lambda path, av: path)  # noqa: ARG005
    fake_pool = MagicMock(name="pool")
    fake_pool.get.return_value = session
    monkeypatch.setattr(tt_module, "default_pool", lambda: fake_pool)


def _fake_project(irods_path: str = PROJECT_ROOT) -> Any:
    proj = MagicMock(name="Project")
    proj.project_id = uuid4()
    proj.irods_path = irods_path
    return proj


def _fake_client(*, project: Any | None, rows: list[FakeAvuChange] | None = None) -> MagicMock:
    client = MagicMock(name="DuckLakeClient")
    client.find_project_by_path.return_value = project
    client.get_avus_as_of.return_value = rows or []
    return client


def _setup(
    monkeypatch: pytest.MonkeyPatch, rows: list[FakeAvuChange] | None = None
) -> tuple[MagicMock, MagicMock, Any]:
    """Wire a MESA-enabled session, a registered project, and a fake client."""
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    project = _fake_project()
    client = _fake_client(project=project, rows=rows)
    dl_client.set_default_client(client)
    return session, client, project


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------


def test_time_travel_tool_is_registered() -> None:
    from mesa_mcp.server import get_tool

    assert get_tool("mesa_ducklake_time_travel").handler is handle_mesa_ducklake_time_travel


def test_as_of_is_required() -> None:
    with pytest.raises(ValueError):
        TimeTravelInput(irods_path=FILE_PATH)  # type: ignore[call-arg]


async def test_time_travel_requires_auth() -> None:
    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_time_travel(
            TimeTravelInput(irods_path=FILE_PATH, as_of=AS_OF), auth_value=None
        )
    assert exc_info.value.code == "unauthenticated"


async def test_time_travel_errors_when_ducklake_disabled(alice: AuthValue) -> None:
    dl_client.set_default_client(None)

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_time_travel(
            TimeTravelInput(irods_path=FILE_PATH, as_of=AS_OF), auth_value=alice
        )
    assert exc_info.value.code == "ducklake_disabled"


async def test_time_travel_errors_when_path_not_in_project(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ancestor carries mesa.enabled=true => not_mesa_project, no catalog call."""
    session = _fake_session(mesa_root=None)
    _patch_access_and_pool(monkeypatch, session)
    client = _fake_client(project=_fake_project())
    dl_client.set_default_client(client)

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_time_travel(
            TimeTravelInput(irods_path=FILE_PATH, as_of=AS_OF), auth_value=alice
        )
    assert exc_info.value.code == "not_mesa_project"
    client.find_project_by_path.assert_not_called()
    client.get_avus_as_of.assert_not_called()


async def test_time_travel_errors_when_project_not_registered(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AVU present but no catalog row => drift, surfaced as its own code."""
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    client = _fake_client(project=None)
    dl_client.set_default_client(client)

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_time_travel(
            TimeTravelInput(irods_path=FILE_PATH, as_of=AS_OF), auth_value=alice
        )
    assert exc_info.value.code == "time_travel_project_not_registered"
    client.find_project_by_path.assert_called_once_with(PROJECT_ROOT)
    client.get_avus_as_of.assert_not_called()


async def test_time_travel_errors_when_catalog_lookup_fails(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)
    client = _fake_client(project=None)
    client.find_project_by_path.side_effect = RuntimeError("postgres down")
    dl_client.set_default_client(client)

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_time_travel(
            TimeTravelInput(irods_path=FILE_PATH, as_of=AS_OF), auth_value=alice
        )
    assert exc_info.value.code == "time_travel_failed_catalog_lookup"


async def test_time_travel_errors_when_read_fails(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, client, _ = _setup(monkeypatch)
    client.get_avus_as_of.side_effect = RuntimeError("parquet missing")

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_time_travel(
            TimeTravelInput(irods_path=FILE_PATH, as_of=AS_OF), auth_value=alice
        )
    assert exc_info.value.code == "time_travel_failed_read"


# ---------------------------------------------------------------------------
# as_of handling
# ---------------------------------------------------------------------------


async def test_time_travel_by_timestamp(alice: AuthValue, monkeypatch: pytest.MonkeyPatch) -> None:
    session, client, project = _setup(
        monkeypatch, rows=[FakeAvuChange(attribute="a", value="1", snapshot_id=3)]
    )

    result = await handle_mesa_ducklake_time_travel(
        TimeTravelInput(irods_path=FILE_PATH, as_of="2026-09-01T14:00:00+02:00"),
        auth_value=alice,
    )

    # The library gets the normalized UTC instant and the session, so it
    # can pull Parquet from iRODS into its cache.
    client.get_avus_as_of.assert_called_once_with(
        project.project_id, FILE_PATH, AS_OF_DT, session=session
    )
    client.get_history.assert_not_called()

    assert result["project_id"] == str(project.project_id)
    assert result["as_of"] == "2026-09-01T12:00:00Z"
    assert result["count"] == 1
    # Rows are JSON-mode dumps with the same fields the history tool returns.
    assert set(result["rows"][0]) == set(FakeAvuChange.model_fields)
    assert result["rows"][0]["ts"] == "2026-09-01T11:00:00Z"
    assert result["rows"][0]["snapshot_id"] == 3


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
    assert tt_module._parse_as_of(as_of) == AS_OF_DT


@pytest.mark.parametrize(
    "as_of",
    ["2026-09-01T12:00:00Z", "2026-09-01T14:00:00+02:00", "2026-09-01T12:00:00"],
)
def test_parse_as_of_fallback_matches_library_rules(
    as_of: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With mesa-ducklake absent, the local copy gives the same answer."""
    monkeypatch.setitem(sys.modules, "mesa_ducklake.time_travel", None)
    assert tt_module._library_parse_as_of() is tt_module._fallback_parse_as_of
    assert tt_module._parse_as_of(as_of) == AS_OF_DT


@pytest.mark.parametrize("as_of", ["last tuesday", "", "2026-13-01T00:00:00Z"])
async def test_time_travel_rejects_malformed_as_of(
    as_of: str, alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad timestamp fails before any iRODS or catalog call."""
    session, client, _ = _setup(monkeypatch)

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_time_travel(
            TimeTravelInput(irods_path=FILE_PATH, as_of=as_of), auth_value=alice
        )
    assert exc_info.value.code == "invalid_argument"
    session.metadata.get.assert_not_called()
    client.find_project_by_path.assert_not_called()


@pytest.mark.parametrize("as_of", ["42", " 7 ", "20260901"])
async def test_time_travel_rejects_snapshot_id(
    as_of: str, alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """parse_as_of has no snapshot-id form, so an all-digit as_of is refused, not guessed."""
    session, client, _ = _setup(monkeypatch)

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_time_travel(
            TimeTravelInput(irods_path=FILE_PATH, as_of=as_of), auth_value=alice
        )
    assert exc_info.value.code == "invalid_argument"
    assert "Snapshot ids are not supported" in exc_info.value.message
    session.metadata.get.assert_not_called()
    client.get_avus_as_of.assert_not_called()


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


async def test_time_travel_filters_by_attribute(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(
        monkeypatch,
        rows=[
            FakeAvuChange(attribute="envo.biome", value="x"),
            FakeAvuChange(attribute="other", value="y"),
            FakeAvuChange(attribute="envo.biome", value="z"),
            FakeAvuChange(attribute="envo.biomes", value="prefix-only"),
        ],
    )

    result = await handle_mesa_ducklake_time_travel(
        TimeTravelInput(irods_path=FILE_PATH, as_of=AS_OF, attribute="envo.biome"),
        auth_value=alice,
    )

    assert result["count"] == 2
    assert [r["value"] for r in result["rows"]] == ["x", "z"]


async def test_time_travel_filters_by_unit(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(
        monkeypatch,
        rows=[
            FakeAvuChange(value="curie", unit="ENVO:01000174"),
            FakeAvuChange(value="bare", unit=""),
            FakeAvuChange(value="other-curie", unit="ENVO:00000446"),
        ],
    )

    result = await handle_mesa_ducklake_time_travel(
        TimeTravelInput(irods_path=FILE_PATH, as_of=AS_OF, unit="ENVO:01000174"),
        auth_value=alice,
    )
    assert [r["value"] for r in result["rows"]] == ["curie"]

    # Empty string is a real filter (AVUs with no unit), not "no filter".
    result = await handle_mesa_ducklake_time_travel(
        TimeTravelInput(irods_path=FILE_PATH, as_of=AS_OF, unit=""), auth_value=alice
    )
    assert [r["value"] for r in result["rows"]] == ["bare"]


async def test_time_travel_filters_combine(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(
        monkeypatch,
        rows=[
            FakeAvuChange(attribute="a", unit="u1"),
            FakeAvuChange(attribute="a", unit="u2"),
            FakeAvuChange(attribute="b", unit="u2"),
        ],
    )

    result = await handle_mesa_ducklake_time_travel(
        TimeTravelInput(irods_path=FILE_PATH, as_of=AS_OF, attribute="a", unit="u2"),
        auth_value=alice,
    )
    assert result["count"] == 1
    assert (result["rows"][0]["attribute"], result["rows"][0]["unit"]) == ("a", "u2")


# ---------------------------------------------------------------------------
# Limit and ordering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(100, 100), (1, 1), (0, 1), (-5, 1), (1000, 1000), (1001, 1000), (5000, 1000)],
)
def test_clamp_limit(requested: int, expected: int) -> None:
    assert tt_module._clamp_limit(requested) == expected


async def test_time_travel_limit_is_capped(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(monkeypatch, rows=[FakeAvuChange(value=f"{i:05d}") for i in range(MAX_LIMIT + 200)])

    result = await handle_mesa_ducklake_time_travel(
        TimeTravelInput(irods_path=FILE_PATH, as_of=AS_OF, limit=5000), auth_value=alice
    )

    assert result["count"] == MAX_LIMIT
    assert len(result["rows"]) == MAX_LIMIT


async def test_time_travel_default_limit(alice: AuthValue, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(monkeypatch, rows=[FakeAvuChange(value=f"{i:03d}") for i in range(150)])

    result = await handle_mesa_ducklake_time_travel(
        TimeTravelInput(irods_path=FILE_PATH, as_of=AS_OF), auth_value=alice
    )
    assert result["count"] == 100


async def test_time_travel_limit_truncates_after_filtering_in_stable_order(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`limit` keeps the first matches by (attribute, value, unit), whatever the read order."""
    _setup(
        monkeypatch,
        rows=[
            FakeAvuChange(attribute="want", value="4"),
            FakeAvuChange(attribute="other", value="0"),
            FakeAvuChange(attribute="want", value="2"),
            FakeAvuChange(attribute="other", value="1"),
            FakeAvuChange(attribute="want", value="3"),
        ],
    )

    result = await handle_mesa_ducklake_time_travel(
        TimeTravelInput(irods_path=FILE_PATH, as_of=AS_OF, attribute="want", limit=2),
        auth_value=alice,
    )

    assert [r["value"] for r in result["rows"]] == ["2", "3"]
    assert result["count"] == 2


async def test_time_travel_resolves_project_from_nested_path(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The catalog lookup uses the *project root*, not the queried path."""
    _, client, _ = _setup(monkeypatch)

    nested = f"{PROJECT_ROOT}/a/b/c/deep.txt"
    await handle_mesa_ducklake_time_travel(
        TimeTravelInput(irods_path=nested, as_of=AS_OF), auth_value=alice
    )

    client.find_project_by_path.assert_called_once_with(PROJECT_ROOT)
    # ...but the AVU read is for the queried path itself.
    assert client.get_avus_as_of.call_args.args[1] == nested
