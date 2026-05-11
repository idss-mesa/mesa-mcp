"""Unit tests for ``ds_make_directory``, ``ds_delete_file``, ``ds_move_file``,
``ds_copy_file``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mesa_mcp.errors import ToolError
from mesa_mcp.server import MesaServer

from .conftest import make_entry

# ---------------------------------------------------------------------------
# ds_make_directory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_make_directory_creates_and_returns_entry(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    mock_session.collections.create = MagicMock()
    # After creation, resolve_target should succeed.
    coll = MagicMock()
    coll.path = "/iplant/home/alice/newdir"
    coll.name = "newdir"
    mock_session.collections.get.return_value = coll

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_make_directory",
            {"path": "/iplant/home/alice/newdir"},
        )
    mock_session.collections.create.assert_called_once_with(
        "/iplant/home/alice/newdir"
    )
    assert result["path"] == "/iplant/home/alice/newdir"
    assert result["entry_info"]["type"] == "directory"


@pytest.mark.asyncio
async def test_make_directory_anonymous_rejected(
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
                "ds_make_directory",
                {"path": "/iplant/home/shared/x"},
            )
    assert exc.value.code == "forbidden"


# ---------------------------------------------------------------------------
# ds_delete_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_file_unlinks_data_object(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    mock_session.collections.get.side_effect = RuntimeError("not a coll")
    obj = make_entry("/iplant/home/alice/file.txt", size=10)
    mock_session.data_objects.get.return_value = obj
    mock_session.data_objects.unlink = MagicMock()

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_delete_file",
            {"path": "/iplant/home/alice/file.txt"},
        )
    mock_session.data_objects.unlink.assert_called_once_with(
        "/iplant/home/alice/file.txt", force=True
    )
    assert result["path"] == "/iplant/home/alice/file.txt"
    assert result["entry_info"]["type"] == "file"


@pytest.mark.asyncio
async def test_delete_file_recurse_removes_collection(
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
    mock_session.collections.remove = MagicMock()

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_delete_file",
            {"path": "/iplant/home/alice/dir"},
        )
    mock_session.collections.remove.assert_called_once_with(
        "/iplant/home/alice/dir", recurse=True, force=True
    )
    assert result["entry_info"]["type"] == "directory"


@pytest.mark.asyncio
async def test_delete_anonymous_rejected(
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
                "ds_delete_file",
                {"path": "/iplant/home/shared/x"},
            )
    assert exc.value.code == "forbidden"


# ---------------------------------------------------------------------------
# ds_move_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_move_file_for_data_object_calls_data_objects_move(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    # Initial resolve for the source path.
    mock_session.collections.get.side_effect = [
        RuntimeError("not a coll"),
        RuntimeError("not a coll"),
    ]
    src_obj = make_entry("/iplant/home/alice/old.txt", size=10)
    dst_obj = make_entry("/iplant/home/alice/new.txt", size=10)
    mock_session.data_objects.get.side_effect = [src_obj, dst_obj]
    mock_session.data_objects.move = MagicMock()

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_move_file",
            {
                "old_path": "/iplant/home/alice/old.txt",
                "new_path": "/iplant/home/alice/new.txt",
            },
        )
    mock_session.data_objects.move.assert_called_once_with(
        "/iplant/home/alice/old.txt",
        "/iplant/home/alice/new.txt",
    )
    assert result["old_path"] == "/iplant/home/alice/old.txt"
    assert result["new_path"] == "/iplant/home/alice/new.txt"


# ---------------------------------------------------------------------------
# ds_copy_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_copy_file_for_data_object_streams_content(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    # Source resolves to a data object; destination resolves after copy.
    mock_session.collections.get.side_effect = [
        RuntimeError("not a coll"),
        RuntimeError("not a coll"),
    ]
    src_obj = make_entry("/iplant/home/alice/src.txt", size=4)
    dst_obj = make_entry("/iplant/home/alice/dst.txt", size=4)
    mock_session.data_objects.get.side_effect = [src_obj, dst_obj]

    # ``open()`` returns a CM that yields a read/write file. Two opens,
    # one for source ("r"), one for destination ("w").
    fp_src = MagicMock()
    fp_src.read.side_effect = [b"data", b""]
    cm_src = MagicMock()
    cm_src.__enter__.return_value = fp_src
    cm_src.__exit__.return_value = False

    fp_dst = MagicMock()
    cm_dst = MagicMock()
    cm_dst.__enter__.return_value = fp_dst
    cm_dst.__exit__.return_value = False

    mock_session.data_objects.open.side_effect = [cm_src, cm_dst]

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_copy_file",
            {
                "source_path": "/iplant/home/alice/src.txt",
                "destination_path": "/iplant/home/alice/dst.txt",
            },
        )
    fp_dst.write.assert_called_once_with(b"data")
    assert result["source_path"] == "/iplant/home/alice/src.txt"
    assert result["destination_path"] == "/iplant/home/alice/dst.txt"
    assert len(result["source_entry_info_list"]) == 1
    assert len(result["copied_entry_info_list"]) == 1
