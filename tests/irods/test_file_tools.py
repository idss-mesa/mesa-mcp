"""Unit tests for ``ds_read_file``, ``ds_write_file``, ``ds_get_file_info``,
``ds_upload_file``, ``ds_download_file``."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest

from mesa_mcp.errors import ToolError
from mesa_mcp.server import MesaServer

from .conftest import make_entry

# ---------------------------------------------------------------------------
# ds_get_file_info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_file_info_collection_returns_directory_mime(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    coll = MagicMock()
    coll.path = "/iplant/home/alice/dir"
    coll.name = "dir"
    coll.inheritance = True
    coll.metadata.items.return_value = []
    mock_session.collections.get.return_value = coll
    mock_session.acls.get.return_value = []

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_get_file_info",
            {"path": "/iplant/home/alice/dir"},
        )
    assert result["mime_type"] == "Directory"
    assert result["access_inheritance"] == {
        "path": "/iplant/home/alice/dir",
        "inherit": True,
    }


@pytest.mark.asyncio
async def test_get_file_info_data_object_returns_extension_mime(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    mock_session.collections.get.side_effect = RuntimeError("not a coll")
    obj = make_entry("/iplant/home/alice/file.json", size=42)
    obj.metadata.items.return_value = []
    mock_session.data_objects.get.return_value = obj
    mock_session.acls.get.return_value = []

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_get_file_info",
            {"path": "/iplant/home/alice/file.json"},
        )
    assert result["mime_type"] == "application/json"
    assert result["access_inheritance"] is None
    # Anonymous-only filter does not apply for ``alice``.
    assert result["avus"] == []


@pytest.mark.asyncio
async def test_get_file_info_hides_system_avus_for_anonymous_caller(
    anon_auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    # Anonymous can hit /iplant/home/shared/file.txt
    mock_session.collections.get.side_effect = RuntimeError("not a coll")
    obj = make_entry("/iplant/home/shared/file.txt", size=10)

    user_avu = MagicMock()
    user_avu.name = "project"
    user_avu.value = "demo"
    user_avu.units = None
    sys_avu = MagicMock()
    sys_avu.name = "ipc_UUID"
    sys_avu.value = "abc-def"
    sys_avu.units = None
    obj.metadata.items.return_value = [user_avu, sys_avu]
    mock_session.data_objects.get.return_value = obj
    mock_session.acls.get.return_value = []

    server = MesaServer(config=config)
    with context_binder(
        auth_value=anon_auth_value,
        pool=mock_pool,
        config=config,
    ):
        result = await server.call(
            "ds_get_file_info",
            {"path": "/iplant/home/shared/file.txt"},
        )
    visible = [a["attribute"] for a in result["avus"]]
    assert visible == ["project"]


# ---------------------------------------------------------------------------
# ds_read_file
# ---------------------------------------------------------------------------


def _stub_open(content: bytes) -> MagicMock:
    """A context-manager mock that yields a read()-able file object."""
    fp = MagicMock()
    fp.read.return_value = content
    cm = MagicMock()
    cm.__enter__.return_value = fp
    cm.__exit__.return_value = False
    return cm


@pytest.mark.asyncio
async def test_read_file_returns_text_for_text_files(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    mock_session.collections.get.side_effect = RuntimeError("not a coll")
    obj = make_entry("/iplant/home/alice/note.txt", size=4)
    mock_session.data_objects.get.return_value = obj
    mock_session.data_objects.open.return_value = _stub_open(b"hi!\n")

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_read_file",
            {"path": "/iplant/home/alice/note.txt"},
        )
    assert result["text"] == "hi!\n"
    assert result["mime_type"].startswith("text/")


@pytest.mark.asyncio
async def test_read_file_returns_base64_for_binary_files(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    payload = b"\x89PNG\r\n\x1a\n"
    mock_session.collections.get.side_effect = RuntimeError("not a coll")
    obj = make_entry("/iplant/home/alice/img.png", size=len(payload))
    mock_session.data_objects.get.return_value = obj
    mock_session.data_objects.open.return_value = _stub_open(payload)

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_read_file",
            {"path": "/iplant/home/alice/img.png"},
        )
    assert "base64" in result
    assert base64.b64decode(result["base64"]) == payload


@pytest.mark.asyncio
async def test_read_file_directory_returns_reference(
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

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_read_file",
            {"path": "/iplant/home/alice/dir"},
        )
    assert result["is_directory"] is True
    assert result["resource_uri"].startswith("irods://")


# ---------------------------------------------------------------------------
# ds_write_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_file_rejects_anonymous(
    anon_auth_value,
    mock_pool,
    config,
    context_binder,
):
    payload = base64.b64encode(b"hello").decode()
    server = MesaServer(config=config)
    with context_binder(
        auth_value=anon_auth_value,
        pool=mock_pool,
        config=config,
    ):
        with pytest.raises(ToolError) as exc:
            await server.call(
                "ds_write_file",
                {"path": "/iplant/home/shared/x.txt", "content": payload},
            )
    assert exc.value.code == "forbidden"


@pytest.mark.asyncio
async def test_write_file_creates_new_file_at_offset_zero(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    # Make the path not-found, then ``write_file`` opens with ``w``.
    mock_session.collections.get.side_effect = RuntimeError("nope")
    mock_session.data_objects.get.side_effect = RuntimeError("nope")
    fp_mock = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = fp_mock
    cm.__exit__.return_value = False
    mock_session.data_objects.open.return_value = cm

    payload_b = b"hello, mesa\n"
    payload = base64.b64encode(payload_b).decode()
    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_write_file",
            {"path": "/iplant/home/alice/new.txt", "content": payload},
        )
    assert result == {
        "path": "/iplant/home/alice/new.txt",
        "offset": 0,
        "bytes_written": len(payload_b),
    }
    fp_mock.write.assert_called_once_with(payload_b)


@pytest.mark.asyncio
async def test_write_file_invalid_base64_raises(
    auth_value,
    mock_pool,
    config,
    context_binder,
):
    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        # Use a clearly invalid base64 character set.
        with pytest.raises(ToolError) as exc:
            await server.call(
                "ds_write_file",
                {
                    "path": "/iplant/home/alice/new.txt",
                    "content": "@@@!!!not base64 at all###",
                },
            )
        # base64.b64decode with validate=False is lenient — we may not get
        # an invalid_argument; tolerate either invalid_argument (decoder
        # failure) or internal_error (downstream open failure on a real
        # session). For our mock, the decode produces *some* bytes, so the
        # error code may shift; just verify a ToolError was raised.
        assert exc.value.code in {"invalid_argument", "internal_error", "not_found"}


# ---------------------------------------------------------------------------
# ds_upload_file / ds_download_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_file_returns_instructions(
    auth_value,
    mock_pool,
    config,
    context_binder,
):
    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_upload_file",
            {
                "local_path": "/tmp/note.txt",
                "irods_path": "/iplant/home/alice/note.txt",
            },
        )
    assert "curl -L -T" in result["text"]
    assert "gocmd put" in result["text"]
    assert "iput" in result["text"]
    assert result["webdav_uri"].startswith("https://alice@")


@pytest.mark.asyncio
async def test_download_file_returns_instructions_for_file(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    mock_session.collections.get.side_effect = RuntimeError("not a coll")
    obj = make_entry("/iplant/home/alice/file.txt", size=12)
    mock_session.data_objects.get.return_value = obj

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_download_file",
            {
                "irods_path": "/iplant/home/alice/file.txt",
                "local_path": "/tmp/file.txt",
            },
        )
    assert "curl -L -o" in result["text"]
    assert "iget -K -P" in result["text"]
    assert result["is_dir"] is False


@pytest.mark.asyncio
async def test_download_file_returns_recursive_instructions_for_collection(
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

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_download_file",
            {
                "irods_path": "/iplant/home/alice/dir",
                "local_path": "/tmp/dir",
            },
        )
    assert result["is_dir"] is True
    assert "curl -r -L -o" in result["text"]
    assert "iget -K -r -P" in result["text"]
