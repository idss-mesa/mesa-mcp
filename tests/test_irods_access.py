"""Unit tests for :mod:`mesa_mcp.irods.access`."""

from __future__ import annotations

import pytest

from mesa_mcp.auth import AuthValue
from mesa_mcp.errors import ToolError
from mesa_mcp.irods.access import assert_allowed, is_within, normalize

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def alice() -> AuthValue:
    return AuthValue(username="alice", zone="iplant", password="hunter2")


@pytest.fixture
def anon() -> AuthValue:
    return AuthValue(username="anonymous", zone="iplant", auth_scheme="anonymous")


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


def test_normalize_collapses_double_slashes():
    assert normalize("/iplant//home//alice") == "/iplant/home/alice"


def test_normalize_resolves_dot_segments():
    assert normalize("/iplant/home/./alice") == "/iplant/home/alice"


def test_normalize_resolves_double_dot_segments():
    assert normalize("/iplant/home/alice/../alice") == "/iplant/home/alice"


def test_normalize_strips_trailing_slash():
    assert normalize("/iplant/home/alice/") == "/iplant/home/alice"


def test_normalize_keeps_root_slash():
    assert normalize("/") == "/"


def test_normalize_rejects_empty():
    with pytest.raises(ToolError) as exc:
        normalize("")
    assert exc.value.code == "invalid_argument"


def test_normalize_rejects_whitespace_only():
    with pytest.raises(ToolError):
        normalize("   ")


def test_normalize_rejects_relative_path():
    with pytest.raises(ToolError) as exc:
        normalize("home/alice")
    assert exc.value.code == "invalid_argument"


def test_normalize_strips_icommands_prefix():
    assert normalize("i:/iplant/home/alice") == "/iplant/home/alice"


def test_normalize_prevents_escape_above_root():
    # `/..` collapses to `/`, so the result is the zone root — still within
    # `/` which is *not* a permitted accessible path, so the access check
    # will reject it. We assert normalize doesn't blow up.
    assert normalize("/..") == "/"
    assert normalize("/../..") == "/"
    assert normalize("/../etc") == "/etc"


# ---------------------------------------------------------------------------
# is_within
# ---------------------------------------------------------------------------


def test_is_within_exact_match():
    assert is_within("/iplant/home/alice", "/iplant/home/alice")


def test_is_within_subdirectory():
    assert is_within("/iplant/home/alice/data", "/iplant/home/alice")


def test_is_within_rejects_sibling_prefix_attack():
    # `/iplant/home/alice2` must NOT be inside `/iplant/home/alice`.
    assert not is_within("/iplant/home/alice2", "/iplant/home/alice")


def test_is_within_rejects_disjoint_path():
    assert not is_within("/iplant/home/bob", "/iplant/home/alice")


def test_is_within_handles_root_with_trailing_slash():
    assert is_within("/iplant/home/alice/x", "/iplant/home/alice/")


# ---------------------------------------------------------------------------
# assert_allowed
# ---------------------------------------------------------------------------


def test_assert_allowed_accepts_home_directly(alice):
    assert assert_allowed("/iplant/home/alice", alice) == "/iplant/home/alice"


def test_assert_allowed_accepts_subpath_of_home(alice):
    result = assert_allowed("/iplant/home/alice/data/file.csv", alice)
    assert result == "/iplant/home/alice/data/file.csv"


def test_assert_allowed_accepts_shared(alice):
    result = assert_allowed("/iplant/home/shared/dataset.csv", alice)
    assert result == "/iplant/home/shared/dataset.csv"


def test_assert_allowed_rejects_sibling_home(alice):
    with pytest.raises(ToolError) as exc:
        assert_allowed("/iplant/home/bob/file.txt", alice)
    assert exc.value.code == "forbidden"
    assert exc.value.details["user"] == "alice"
    assert exc.value.details["path"] == "/iplant/home/bob/file.txt"


def test_assert_allowed_rejects_sibling_prefix_attack(alice):
    # `/iplant/home/alice2` is NOT inside `/iplant/home/alice`.
    with pytest.raises(ToolError) as exc:
        assert_allowed("/iplant/home/alice2/file.txt", alice)
    assert exc.value.code == "forbidden"


def test_assert_allowed_rejects_path_escape_attempt(alice):
    with pytest.raises(ToolError) as exc:
        assert_allowed("/iplant/home/alice/../bob/file.txt", alice)
    assert exc.value.code == "forbidden"


def test_assert_allowed_rejects_double_dot_escape_to_root(alice):
    with pytest.raises(ToolError):
        assert_allowed("/iplant/home/alice/../../..", alice)


def test_assert_allowed_normalises_returned_path(alice):
    """Returned path is the normalised form, not the raw input."""
    result = assert_allowed("/iplant/home/alice//data//x.txt", alice)
    assert result == "/iplant/home/alice/data/x.txt"


def test_assert_allowed_strips_trailing_slash_in_return(alice):
    result = assert_allowed("/iplant/home/alice/data/", alice)
    assert result == "/iplant/home/alice/data"


# ---------------------------------------------------------------------------
# Anonymous caller restrictions
# ---------------------------------------------------------------------------


def test_anonymous_can_access_shared(anon):
    result = assert_allowed("/iplant/home/shared/public.csv", anon)
    assert result == "/iplant/home/shared/public.csv"


def test_anonymous_cannot_access_anonymous_home(anon):
    """Anonymous users do not get a home directory in accessible_paths."""
    with pytest.raises(ToolError) as exc:
        assert_allowed("/iplant/home/anonymous/file.txt", anon)
    assert exc.value.code == "forbidden"


def test_anonymous_cannot_access_another_user_home(anon):
    with pytest.raises(ToolError):
        assert_allowed("/iplant/home/alice/file.txt", anon)


def test_anonymous_cannot_access_zone_root(anon):
    with pytest.raises(ToolError):
        assert_allowed("/iplant", anon)
