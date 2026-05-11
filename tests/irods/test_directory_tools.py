"""Unit tests for the directory-listing ``ds_*`` tools.

Covers ``ds_list_allowed_directories``, ``ds_list_directory``,
``ds_list_directory_details``, ``ds_directory_tree`` and ``ds_search_files``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mesa_mcp.config import Config
from mesa_mcp.errors import ToolError
from mesa_mcp.server import MesaServer

from .conftest import make_entry

# ---------------------------------------------------------------------------
# ds_list_allowed_directories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_allowed_directories_returns_home_and_shared(
    auth_value,
    mock_pool,
    config,
    context_binder,
):
    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call("ds_list_allowed_directories")
    paths = [d["path"] for d in result["directories"]]
    assert "/iplant/home/alice" in paths
    assert "/iplant/home/shared" in paths
    # Every entry exposes a list of allowed APIs and an ``allowed`` flag.
    for d in result["directories"]:
        assert d["allowed"] is True
        assert "ds_list_directory" in d["apis_allowed"]


@pytest.mark.asyncio
async def test_list_allowed_directories_anonymous_omits_home(
    anon_auth_value,
    mock_pool,
    config,
    context_binder,
):
    server = MesaServer(config=config)
    with context_binder(auth_value=anon_auth_value, pool=mock_pool, config=config):
        result = await server.call("ds_list_allowed_directories")
    paths = [d["path"] for d in result["directories"]]
    assert "/iplant/home/anonymous" not in paths
    assert "/iplant/home/shared" in paths


# ---------------------------------------------------------------------------
# ds_list_directory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_directory_paginates_and_emits_uris(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    coll = MagicMock(name="alice-home")
    coll.path = "/iplant/home/alice"
    coll.name = "alice"
    coll.subcollections = [
        make_entry("/iplant/home/alice/dirA", kind="collection", name="dirA"),
    ]
    coll.data_objects = [
        make_entry("/iplant/home/alice/file1.txt", size=10, name="file1.txt"),
        make_entry("/iplant/home/alice/file2.txt", size=20, name="file2.txt"),
    ]
    mock_session.collections.get.return_value = coll

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_list_directory",
            {"path": "/iplant/home/alice"},
        )
    assert result["total"] == 3
    assert result["limit"] == 100
    assert result["offset"] == 0
    assert len(result["directory_entries"]) == 3
    # WebDAV URI is minted into every entry.
    for entry in result["directory_entries"]:
        assert entry["webdav_uri"].startswith("https://alice@")
        assert entry["resource_uri"].startswith("irods://")


@pytest.mark.asyncio
async def test_list_directory_clamps_limit_to_500(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    coll = MagicMock()
    coll.path = "/iplant/home/alice"
    coll.subcollections = []
    coll.data_objects = []
    mock_session.collections.get.return_value = coll

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_list_directory",
            {"path": "/iplant/home/alice", "limit": 9000},
        )
    assert result["limit"] == 500


@pytest.mark.asyncio
async def test_list_directory_rejects_when_target_is_data_object(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    # Make ``collections.get`` fail so resolve_target falls through to
    # data_object — which means ``ds_list_directory`` should reject.
    mock_session.collections.get.side_effect = RuntimeError("not a collection")
    obj = make_entry("/iplant/home/alice/file.txt", size=10)
    mock_session.data_objects.get.return_value = obj

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        with pytest.raises(ToolError) as exc:
            await server.call(
                "ds_list_directory",
                {"path": "/iplant/home/alice/file.txt"},
            )
    assert exc.value.code == "invalid_argument"


@pytest.mark.asyncio
async def test_list_directory_rejects_path_outside_access(
    auth_value,
    mock_pool,
    config,
    context_binder,
):
    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        with pytest.raises(ToolError) as exc:
            await server.call(
                "ds_list_directory",
                {"path": "/iplant/home/bob"},
            )
    assert exc.value.code == "forbidden"


# ---------------------------------------------------------------------------
# ds_list_directory_details
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_directory_details_emits_accesses(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    coll = MagicMock()
    coll.path = "/iplant/home/alice"
    coll.name = "alice"
    coll.subcollections = []

    obj = make_entry("/iplant/home/alice/f.txt", size=5)
    coll.data_objects = [obj]
    mock_session.collections.get.return_value = coll

    # Provide ACLs through ``session.acls.get``.
    access_obj = MagicMock()
    access_obj.user_name = "alice"
    access_obj.access_name = "own"
    access_obj.user_zone = "iplant"
    access_obj.path = "/iplant/home/alice/f.txt"
    mock_session.acls.get.return_value = [access_obj]

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_list_directory_details",
            {"path": "/iplant/home/alice"},
        )
    assert result["total"] == 1
    entry = result["directory_entries"][0]
    assert entry["accesses"] == [
        {
            "user_name": "alice",
            "user_zone": "iplant",
            "access_name": "own",
            "path": "/iplant/home/alice/f.txt",
        }
    ]


# ---------------------------------------------------------------------------
# ds_directory_tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_directory_tree_recurses_to_max_depth(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    # Build a tiny tree: alice/ → sub1/ → leaf.txt
    leaf = make_entry("/iplant/home/alice/sub1/leaf.txt", size=12, name="leaf.txt")
    sub1 = MagicMock()
    sub1.path = "/iplant/home/alice/sub1"
    sub1.name = "sub1"
    sub1.subcollections = []
    sub1.data_objects = [leaf]

    root = MagicMock()
    root.path = "/iplant/home/alice"
    root.name = "alice"
    root.subcollections = [sub1]
    root.data_objects = []
    mock_session.collections.get.return_value = root

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_directory_tree",
            {"path": "/iplant/home/alice", "depth": 3},
        )

    children = result["directory_entries"]
    assert len(children) == 1
    sub_entry = children[0]
    assert sub_entry["entry_info"]["name"] == "sub1"
    assert sub_entry["directory_entries"][0]["entry_info"]["name"] == "leaf.txt"


@pytest.mark.asyncio
async def test_directory_tree_clamps_depth(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    root = MagicMock()
    root.path = "/iplant/home/alice"
    root.subcollections = []
    root.data_objects = []
    mock_session.collections.get.return_value = root

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        # Depth way above the cap should clamp silently.
        result = await server.call(
            "ds_directory_tree",
            {"path": "/iplant/home/alice", "depth": 999},
        )
    assert result["directory_entries"] == []


# ---------------------------------------------------------------------------
# ds_search_files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_files_requires_wildcard(
    auth_value,
    mock_pool,
    config,
    context_binder,
):
    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        with pytest.raises(ToolError) as exc:
            await server.call(
                "ds_search_files",
                {"path": "/iplant/home/alice/file.txt"},
            )
    assert exc.value.code == "invalid_argument"


@pytest.mark.asyncio
async def test_search_files_returns_empty_when_query_unavailable(
    auth_value,
    mock_pool,
    mock_session,
    config,
    context_binder,
):
    # ``session.query`` returns a MagicMock by default; the query may raise
    # depending on the test double's filter semantics. We accept an empty
    # match list rather than an error.
    mock_session.query.return_value.filter.return_value = iter([])

    server = MesaServer(config=config)
    with context_binder(auth_value=auth_value, pool=mock_pool, config=config):
        result = await server.call(
            "ds_search_files",
            {"path": "/iplant/home/alice/*.txt"},
        )
    assert result["search_path"] == "/iplant/home/alice/*.txt"
    assert result["matching_entries"] == []


# ---------------------------------------------------------------------------
# Smoke: every ds_* tool refuses calls without an AuthValue bound.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_without_auth_raises_unauthenticated(config: Config):
    server = MesaServer(config=config)
    with pytest.raises(ToolError) as exc:
        await server.call("ds_list_directory", {"path": "/iplant/home/alice"})
    assert exc.value.code == "unauthenticated"
