"""Unit tests for ``ds_modify_access`` and ``ds_modify_access_inheritance``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mesa_mcp.errors import ToolError
from mesa_mcp.server import MesaServer

from .conftest import make_entry


@pytest.mark.asyncio
async def test_modify_access_for_valid_level_sets_acl(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    mock_session.collections.get.side_effect = RuntimeError("not a coll")
    obj = make_entry("/iplant/home/alice/file.txt", size=10)
    mock_session.data_objects.get.return_value = obj
    mock_session.acls.set = MagicMock()

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_modify_access",
            {
                "access_level": "read",
                "user_or_group": "bob",
                "path": "/iplant/home/alice/file.txt",
            },
        )
    assert result == {
        "path": "/iplant/home/alice/file.txt",
        "user_name": "bob",
        "user_zone": "iplant",
        "access_level": "read",
    }
    args, kwargs = mock_session.acls.set.call_args
    assert kwargs.get("recursive") is False


@pytest.mark.asyncio
async def test_modify_access_rejects_unknown_level(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        with pytest.raises(ToolError) as exc:
            await server.call(
                "ds_modify_access",
                {
                    "access_level": "supersecret",
                    "user_or_group": "bob",
                    "path": "/iplant/home/alice/file.txt",
                },
            )
    assert exc.value.code == "invalid_argument"


@pytest.mark.asyncio
async def test_modify_access_parses_user_at_zone(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    mock_session.collections.get.side_effect = RuntimeError("not a coll")
    obj = make_entry("/iplant/home/alice/file.txt", size=10)
    mock_session.data_objects.get.return_value = obj
    mock_session.acls.set = MagicMock()

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_modify_access",
            {
                "access_level": "own",
                "user_or_group": "carol#tempZone",
                "path": "/iplant/home/alice/file.txt",
            },
        )
    assert result["user_name"] == "carol"
    assert result["user_zone"] == "tempZone"


@pytest.mark.asyncio
async def test_modify_access_anonymous_rejected(
    anon_auth_value,
    mock_pool,
    config,
    context_binder,
):
    server = MesaServer(config=config)
    with context_binder(
        auth_value=anon_auth_value,
        pool=mock_pool,
        config=config,
    ):
        with pytest.raises(ToolError) as exc:
            await server.call(
                "ds_modify_access",
                {
                    "access_level": "read",
                    "user_or_group": "bob",
                    "path": "/iplant/home/shared/x",
                },
            )
    assert exc.value.code == "forbidden"


# ---------------------------------------------------------------------------
# ds_modify_access_inheritance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_modify_access_inheritance_sets_inherit(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    coll = MagicMock()
    coll.path = "/iplant/home/alice/dir"
    coll.name = "dir"
    mock_session.collections.get.return_value = coll
    mock_session.acls.set = MagicMock()

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_modify_access_inheritance",
            {
                "path": "/iplant/home/alice/dir",
                "inherit": True,
                "recurse": True,
            },
        )
    assert result == {"path": "/iplant/home/alice/dir", "inherit": True}
    # The first positional arg should be an iRODSAccess with access_name "inherit".
    args, kwargs = mock_session.acls.set.call_args
    assert kwargs.get("recursive") is True


@pytest.mark.asyncio
async def test_modify_access_inheritance_noinherit_flag(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    coll = MagicMock()
    coll.path = "/iplant/home/alice/dir"
    coll.name = "dir"
    mock_session.collections.get.return_value = coll
    mock_session.acls.set = MagicMock()

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_modify_access_inheritance",
            {"path": "/iplant/home/alice/dir", "inherit": False},
        )
    assert result == {"path": "/iplant/home/alice/dir", "inherit": False}
