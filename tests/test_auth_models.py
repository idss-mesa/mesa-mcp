"""Unit tests for :class:`mesa_mcp.auth.models.AuthValue`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mesa_mcp.auth import AuthValue

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_native_auth_value_derives_paths():
    av = AuthValue(username="alice", zone="iplant", password="hunter2")
    assert av.home_path == "/iplant/home/alice"
    assert av.shared_path == "/iplant/home/shared"
    assert av.auth_scheme == "native"
    assert av.is_anonymous() is False


def test_anonymous_via_scheme_has_anonymous_home():
    av = AuthValue(username="anonymous", zone="iplant", auth_scheme="anonymous")
    assert av.is_anonymous() is True
    assert av.home_path == "/iplant/home/anonymous"


def test_anonymous_via_username_has_anonymous_home_even_with_native_scheme():
    av = AuthValue(username="anonymous", zone="iplant")
    assert av.is_anonymous() is True
    assert av.home_path == "/iplant/home/anonymous"


def test_authvalue_with_ticket_round_trips():
    av = AuthValue(
        username="alice",
        zone="iplant",
        password="hunter2",
        ticket="abc-123",
    )
    assert av.ticket == "abc-123"


def test_authvalue_with_proxy_user():
    av = AuthValue(
        username="bob",
        zone="iplant",
        password="hunter2",
        proxy_user="admin",
    )
    assert av.proxy_user == "admin"


def test_authvalue_is_frozen():
    av = AuthValue(username="alice", zone="iplant", password="hunter2")
    with pytest.raises(ValidationError):
        av.username = "mallory"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# accessible_paths
# ---------------------------------------------------------------------------


def test_native_user_accessible_paths_include_home_and_shared():
    av = AuthValue(username="alice", zone="iplant", password="hunter2")
    paths = av.accessible_paths()
    assert "/iplant/home/alice" in paths
    assert "/iplant/home/shared" in paths


def test_anonymous_accessible_paths_exclude_home():
    av = AuthValue(username="anonymous", zone="iplant", auth_scheme="anonymous")
    paths = av.accessible_paths()
    assert paths == ["/iplant/home/shared"]


def test_accessible_paths_for_pam_user_matches_native_shape():
    av = AuthValue(
        username="alice",
        zone="iplant",
        password="hunter2",
        auth_scheme="pam",
    )
    paths = av.accessible_paths()
    assert "/iplant/home/alice" in paths
    assert "/iplant/home/shared" in paths


# ---------------------------------------------------------------------------
# cache_key
# ---------------------------------------------------------------------------


def test_cache_key_is_deterministic_for_same_credentials():
    a = AuthValue(username="alice", zone="iplant", password="hunter2")
    b = AuthValue(username="alice", zone="iplant", password="hunter2")
    assert a.cache_key() == b.cache_key()


def test_cache_key_differs_by_password():
    a = AuthValue(username="alice", zone="iplant", password="hunter2")
    b = AuthValue(username="alice", zone="iplant", password="other-pw")
    assert a.cache_key() != b.cache_key()


def test_cache_key_differs_by_username():
    a = AuthValue(username="alice", zone="iplant", password="hunter2")
    b = AuthValue(username="bob", zone="iplant", password="hunter2")
    assert a.cache_key() != b.cache_key()


def test_cache_key_differs_by_zone():
    a = AuthValue(username="alice", zone="iplant", password="hunter2")
    b = AuthValue(username="alice", zone="cyverse", password="hunter2")
    assert a.cache_key() != b.cache_key()


def test_cache_key_differs_by_ticket():
    a = AuthValue(username="alice", zone="iplant", password="hunter2")
    b = AuthValue(username="alice", zone="iplant", password="hunter2", ticket="t1")
    assert a.cache_key() != b.cache_key()


def test_cache_key_differs_by_proxy_user():
    a = AuthValue(username="alice", zone="iplant", password="hunter2")
    b = AuthValue(
        username="alice", zone="iplant", password="hunter2", proxy_user="admin"
    )
    assert a.cache_key() != b.cache_key()


def test_cache_key_never_contains_plaintext_password():
    av = AuthValue(username="alice", zone="iplant", password="hunter2")
    assert "hunter2" not in av.cache_key()


def test_cache_key_is_64_char_hex():
    av = AuthValue(username="alice", zone="iplant", password="hunter2")
    key = av.cache_key()
    assert len(key) == 64
    int(key, 16)  # sanity — raises if non-hex


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------


def test_password_not_in_repr_when_set():
    av = AuthValue(username="alice", zone="iplant", password="hunter2")
    text = repr(av)
    assert "hunter2" not in text
    assert "password" not in text


def test_password_not_in_repr_when_none():
    av = AuthValue(username="anonymous", zone="iplant", auth_scheme="anonymous")
    text = repr(av)
    assert "password" not in text


def test_password_not_in_str_when_set():
    av = AuthValue(username="alice", zone="iplant", password="hunter2")
    assert "hunter2" not in str(av)
