"""Tests for the ``mesa_ducklake_init_project`` MCP tool.

We don't drive the registry or transport here — we call the handler
directly, the same way ``tests/test_ds_avu_tools.py`` exercises the
``ds_*`` tools. iRODS and the DuckLake catalog are mocked at module
boundaries so the test never touches a real PRC session or Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from mesa_mcp.auth import AuthValue
from mesa_mcp.ducklake import client as dl_client
from mesa_mcp.ducklake.tools import init_project as init_project_module
from mesa_mcp.ducklake.tools.init_project import handle_mesa_ducklake_init_project
from mesa_mcp.errors import ToolError


@pytest.fixture
def alice() -> AuthValue:
    return AuthValue(username="alice", zone="iplant", password="hunter2")


@pytest.fixture(autouse=True)
def reset_singleton() -> Any:
    dl_client.set_default_client(None)
    yield
    dl_client.set_default_client(None)


def _fake_session(*, existing_avus: list[dict[str, str]] | None = None) -> MagicMock:
    """Build a session that pretends ``irods_path`` exists as a collection."""
    session = MagicMock(name="iRODSSession")

    # collections.get raises only for missing collections — by default
    # the path "exists".
    session.collections = MagicMock(name="collections")
    session.collections.get.return_value = MagicMock(name="collection-obj")

    # metadata.get returns the supplied AVU list (default empty).
    session.metadata = MagicMock(name="metadata")
    avus = existing_avus or []
    fake_metas = []
    for a in avus:
        m = MagicMock()
        m.name = a["name"]
        m.value = a["value"]
        fake_metas.append(m)
    session.metadata.get.return_value = fake_metas

    return session


def _patch_access_and_pool(monkeypatch: pytest.MonkeyPatch, session: MagicMock) -> None:
    """Make assert_allowed pass-through and default_pool yield the mock session.

    Patches the names *as imported into init_project.py* — patching the
    source modules wouldn't help because the names are already bound.
    """
    monkeypatch.setattr(
        init_project_module,
        "assert_allowed",
        lambda path, av: path,  # noqa: ARG005
    )
    fake_pool = MagicMock(name="pool")
    fake_pool.get.return_value = session
    monkeypatch.setattr(init_project_module, "default_pool", lambda: fake_pool)


def _fake_project(
    irods_path: str = "/iplant/home/alice/proj",
    *,
    project_id=None,
) -> Any:
    """Build a fake Project object matching mesa-ducklake's shape."""
    proj = MagicMock(name="Project")
    proj.project_id = project_id or uuid4()
    proj.irods_path = irods_path
    proj.irods_zone = "iplant"
    proj.ducklake_path = f"{irods_path}/.mesa/ducklake"
    proj.created_at = datetime.now(tz=UTC)
    proj.created_by = "alice"
    proj.status = "active"
    return proj


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_init_project_creates_collection_avu_and_catalog_row(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)

    fake_client = MagicMock(name="DuckLakeClient")
    fake_client.find_project_by_path.return_value = None
    fake_client.register_project.return_value = _fake_project()
    dl_client.set_default_client(fake_client)

    from mesa_mcp.ducklake.tools.init_project import InitProjectInput

    result = await handle_mesa_ducklake_init_project(
        InitProjectInput(irods_path="/iplant/home/alice/proj"),
        auth_value=alice,
    )

    # iRODS collection root inspected.
    session.collections.get.assert_called_once_with("/iplant/home/alice/proj")
    # /.mesa/ducklake/ created.
    session.collections.create.assert_called_once_with(
        "/iplant/home/alice/proj/.mesa/ducklake", recurse=True
    )
    # mesa.enabled AVU set.
    session.metadata.add.assert_called_once()
    add_args = session.metadata.add.call_args.args
    avu = add_args[2]
    assert avu.name == "mesa.enabled"
    assert avu.value == "true"
    # Catalog register called.
    fake_client.register_project.assert_called_once()

    # Response shape.
    assert result["irods_path"] == "/iplant/home/alice/proj"
    assert result["ducklake_path"].endswith("/.mesa/ducklake")
    assert result["status"] == "active"
    assert "project_id" in result


async def test_init_project_returns_existing_project_when_already_registered(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catalog row already exists => find_project_by_path returns it; no register call."""
    session = _fake_session(
        existing_avus=[{"name": "mesa.enabled", "value": "true"}]
    )
    _patch_access_and_pool(monkeypatch, session)

    existing = _fake_project()
    fake_client = MagicMock(name="DuckLakeClient")
    fake_client.find_project_by_path.return_value = existing
    dl_client.set_default_client(fake_client)

    from mesa_mcp.ducklake.tools.init_project import InitProjectInput

    result = await handle_mesa_ducklake_init_project(
        InitProjectInput(irods_path="/iplant/home/alice/proj"),
        auth_value=alice,
    )

    fake_client.register_project.assert_not_called()
    # AVU was already present => metadata.add NOT called.
    session.metadata.add.assert_not_called()
    assert result["project_id"] == str(existing.project_id)


async def test_init_project_idempotent_when_collection_exists(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``collections.create`` raising "already exists" must not fail the tool."""
    session = _fake_session()
    session.collections.create.side_effect = RuntimeError(
        "collection already exists"
    )
    _patch_access_and_pool(monkeypatch, session)

    fake_client = MagicMock(name="DuckLakeClient")
    fake_client.find_project_by_path.return_value = None
    fake_client.register_project.return_value = _fake_project()
    dl_client.set_default_client(fake_client)

    from mesa_mcp.ducklake.tools.init_project import InitProjectInput

    await handle_mesa_ducklake_init_project(
        InitProjectInput(irods_path="/iplant/home/alice/proj"),
        auth_value=alice,
    )
    # No exception == pass.


# ---------------------------------------------------------------------------
# Failure modes (each step produces a distinct ToolError code)
# ---------------------------------------------------------------------------


async def test_init_project_requires_auth() -> None:
    from mesa_mcp.ducklake.tools.init_project import InitProjectInput

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_init_project(
            InitProjectInput(irods_path="/iplant/home/alice/proj"),
            auth_value=None,
        )
    assert exc_info.value.code == "unauthenticated"


async def test_init_project_errors_when_ducklake_disabled(alice: AuthValue) -> None:
    dl_client.set_default_client(None)

    from mesa_mcp.ducklake.tools.init_project import InitProjectInput

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_init_project(
            InitProjectInput(irods_path="/iplant/home/alice/proj"),
            auth_value=alice,
        )
    assert exc_info.value.code == "ducklake_disabled"


async def test_init_project_errors_when_root_missing(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    from irods.exception import CollectionDoesNotExist

    session = _fake_session()
    session.collections.get.side_effect = CollectionDoesNotExist
    _patch_access_and_pool(monkeypatch, session)

    fake_client = MagicMock(name="DuckLakeClient")
    dl_client.set_default_client(fake_client)

    from mesa_mcp.ducklake.tools.init_project import InitProjectInput

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_init_project(
            InitProjectInput(irods_path="/iplant/home/alice/proj"),
            auth_value=alice,
        )
    assert exc_info.value.code == "init_project_failed_root_missing"
    fake_client.register_project.assert_not_called()


async def test_init_project_errors_when_avu_add_fails(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _fake_session()
    session.metadata.add.side_effect = RuntimeError("ACL denied")
    _patch_access_and_pool(monkeypatch, session)

    fake_client = MagicMock(name="DuckLakeClient")
    dl_client.set_default_client(fake_client)

    from mesa_mcp.ducklake.tools.init_project import InitProjectInput

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_init_project(
            InitProjectInput(irods_path="/iplant/home/alice/proj"),
            auth_value=alice,
        )
    assert exc_info.value.code == "init_project_failed_avu_add"
    # We never got to the catalog step.
    fake_client.find_project_by_path.assert_not_called()


async def test_init_project_errors_when_catalog_register_fails(
    alice: AuthValue, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _fake_session()
    _patch_access_and_pool(monkeypatch, session)

    fake_client = MagicMock(name="DuckLakeClient")
    fake_client.find_project_by_path.return_value = None
    fake_client.register_project.side_effect = RuntimeError("UNIQUE violation")
    dl_client.set_default_client(fake_client)

    from mesa_mcp.ducklake.tools.init_project import InitProjectInput

    with pytest.raises(ToolError) as exc_info:
        await handle_mesa_ducklake_init_project(
            InitProjectInput(irods_path="/iplant/home/alice/proj"),
            auth_value=alice,
        )
    assert exc_info.value.code == "init_project_failed_catalog_register"
