"""Unit tests for ``mesa_mcp.irods._helpers`` and ``mesa_mcp.irods.webdav``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._helpers import (
    avu_records,
    entry_info,
    reject_anonymous_write,
    resolve_target,
    split_user_zone,
    target_exists,
)
from mesa_mcp.irods.webdav import (
    make_resource_uri,
    make_webdav_url,
    make_webdav_url_for_user,
    make_webdav_url_with_accesses,
)

# ---------------------------------------------------------------------------
# webdav URL minting
# ---------------------------------------------------------------------------


def test_make_resource_uri_emits_irods_scheme():
    assert make_resource_uri("/iplant/home/alice/file.txt") == (
        "irods:///iplant/home/alice/file.txt"
    )


def test_make_webdav_url_for_anonymous_user():
    url = make_webdav_url_for_user(
        "https://data.cyverse.org/dav/",
        "/iplant/home/shared/foo.txt",
        "anonymous",
    )
    # ``anonymous:`` indicates the empty-password sentinel.
    assert url == "https://anonymous:@data.cyverse.org/dav/iplant/home/shared/foo.txt"


def test_make_webdav_url_for_named_user():
    url = make_webdav_url_for_user(
        "https://data.cyverse.org/dav/",
        "/iplant/home/alice/file.txt",
        "alice",
    )
    assert url == "https://alice@data.cyverse.org/dav/iplant/home/alice/file.txt"


def test_make_webdav_url_percent_encodes_segments():
    url = make_webdav_url_for_user(
        "https://data.cyverse.org/dav/",
        "/iplant/home/alice/my file.txt",
        "alice",
    )
    assert "my%20file.txt" in url


def test_make_webdav_url_anonymous_caller_uses_anonymous_url():
    av = AuthValue(username="anonymous", zone="iplant", auth_scheme="anonymous")
    url = make_webdav_url(
        "https://data.cyverse.org/dav/",
        "/iplant/home/shared/file.txt",
        av,
    )
    assert url.startswith("https://anonymous:@")


def test_make_webdav_url_named_caller_uses_user_url():
    av = AuthValue(username="alice", zone="iplant", password="hunter2")
    url = make_webdav_url(
        "https://data.cyverse.org/dav/",
        "/iplant/home/alice/file.txt",
        av,
    )
    assert url.startswith("https://alice@")


def test_make_webdav_url_with_accesses_prefers_anonymous_when_publicly_readable():
    av = AuthValue(username="alice", zone="iplant", password="hunter2")
    anonymous_access = MagicMock()
    anonymous_access.user_name = "anonymous"
    url = make_webdav_url_with_accesses(
        "https://data.cyverse.org/dav/",
        "/iplant/home/alice/file.txt",
        av,
        [anonymous_access],
    )
    assert url.startswith("https://anonymous:@")


def test_make_webdav_url_with_accesses_falls_back_to_user_when_private():
    av = AuthValue(username="alice", zone="iplant", password="hunter2")
    private_access = MagicMock()
    private_access.user_name = "alice"
    url = make_webdav_url_with_accesses(
        "https://data.cyverse.org/dav/",
        "/iplant/home/alice/file.txt",
        av,
        [private_access],
    )
    assert url.startswith("https://alice@")


def test_make_webdav_url_for_empty_base_returns_empty_string():
    assert make_webdav_url_for_user("", "/iplant/home/x", "anonymous") == ""


# ---------------------------------------------------------------------------
# resolve_target / target_exists
# ---------------------------------------------------------------------------


def test_resolve_target_returns_collection_when_get_collection_succeeds():
    session = MagicMock()
    coll = MagicMock()
    session.collections.get.return_value = coll
    session.data_objects.get.side_effect = AssertionError("must not call")
    kind, model = resolve_target(session, "/iplant/home/alice")
    assert kind == "collection"
    assert model is coll


def test_resolve_target_falls_back_to_data_object_when_collection_lookup_fails():
    session = MagicMock()
    session.collections.get.side_effect = RuntimeError("not a collection")
    obj = MagicMock()
    session.data_objects.get.return_value = obj
    kind, model = resolve_target(session, "/iplant/home/alice/file.txt")
    assert kind == "data_object"
    assert model is obj


def test_resolve_target_raises_not_found_when_both_lookups_fail():
    session = MagicMock()
    session.collections.get.side_effect = RuntimeError("nope")
    session.data_objects.get.side_effect = RuntimeError("nope")
    with pytest.raises(ToolError) as exc:
        resolve_target(session, "/iplant/home/alice/missing")
    assert exc.value.code == "not_found"


def test_target_exists_true_for_existing_collection():
    session = MagicMock()
    session.collections.get.return_value = MagicMock()
    assert target_exists(session, "/iplant/home/alice")


def test_target_exists_false_when_neither_lookup_succeeds():
    session = MagicMock()
    session.collections.get.side_effect = RuntimeError("nope")
    session.data_objects.get.side_effect = RuntimeError("nope")
    assert not target_exists(session, "/iplant/home/alice/missing")


# ---------------------------------------------------------------------------
# entry_info / avu_records
# ---------------------------------------------------------------------------


def test_entry_info_emits_type_for_collection():
    mock = MagicMock()
    mock.path = "/iplant/home/alice"
    mock.name = "alice"
    info = entry_info(mock, "collection")
    assert info["type"] == "directory"
    assert info["name"] == "alice"


def test_entry_info_emits_size_only_for_data_objects():
    mock = MagicMock()
    mock.path = "/iplant/home/alice/file.txt"
    mock.name = "file.txt"
    mock.size = 4242
    info = entry_info(mock, "data_object")
    assert info["type"] == "file"
    assert info["size"] == 4242


def test_avu_records_filters_system_attrs_for_anonymous():
    avu_user = MagicMock(name="user-avu")
    avu_user.name = "project"
    avu_user.value = "demo"
    avu_user.units = None
    avu_system = MagicMock(name="system-avu")
    avu_system.name = "ipc_UUID"
    avu_system.value = "uuid-value"
    avu_system.units = None

    visible = avu_records([avu_user, avu_system], hide_system=True)
    assert [a["attribute"] for a in visible] == ["project"]


# ---------------------------------------------------------------------------
# split_user_zone / reject_anonymous_write
# ---------------------------------------------------------------------------


def test_split_user_zone_with_explicit_zone():
    user, zone = split_user_zone("alice#tempZone", "iplant")
    assert (user, zone) == ("alice", "tempZone")


def test_split_user_zone_falls_back_to_default():
    user, zone = split_user_zone("alice", "iplant")
    assert (user, zone) == ("alice", "iplant")


def test_reject_anonymous_write_raises_forbidden():
    anon = AuthValue(username="anonymous", zone="iplant", auth_scheme="anonymous")
    with pytest.raises(ToolError) as exc:
        reject_anonymous_write(anon, "ds_write_file")
    assert exc.value.code == "forbidden"


def test_reject_anonymous_write_passes_for_named_user():
    av = AuthValue(username="alice", zone="iplant", password="hunter2")
    # No raise.
    reject_anonymous_write(av, "ds_write_file")
