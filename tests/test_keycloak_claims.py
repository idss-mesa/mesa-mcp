"""Typed Keycloak claims and service-account rejection.

Identity mapping used to be duplicated inline in the OIDC verifier and the
trusted-decode header path. These tests pin the single model both now use,
and the rule ported from ``cyverse-de/formation``: a service-account token
authenticates a client, not a person, and must not reach iRODS.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mesa_mcp.auth.claims import SERVICE_ACCOUNT_PREFIX, KeycloakClaims

# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"preferred_username": "alice", "sub": "uuid-1"}, "alice"),
        # preferred_username wins over sub.
        ({"preferred_username": "alice", "sub": "bob"}, "alice"),
        # CyVerse realm suffix stripped: iRODS usernames carry no realm.
        ({"preferred_username": "alice@CyVerse"}, "alice"),
        ({"sub": "uuid-1"}, "uuid-1"),
        # An EMPTY preferred_username must not authenticate as "" — it
        # falls through to sub exactly like an absent claim.
        ({"preferred_username": "", "sub": "uuid-1"}, "uuid-1"),
        ({"preferred_username": "   ", "sub": "uuid-1"}, "uuid-1"),
    ],
)
def test_username_resolution(payload, expected):
    assert KeycloakClaims.from_payload(payload).username() == expected


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"preferred_username": ""},
        {"preferred_username": "@CyVerse"},  # suffix only, no local part
        {"sub": ""},
    ],
)
def test_username_is_none_when_the_token_names_nobody(payload):
    """No identity returns None so the caller chooses how to fail."""
    assert KeycloakClaims.from_payload(payload).username() is None


def test_non_string_claims_are_ignored():
    """A malformed token must not crash identity extraction."""
    claims = KeycloakClaims.from_payload(
        {"preferred_username": 12345, "sub": ["not", "a", "string"], "exp": "soon"}
    )
    assert claims.username() is None
    assert claims.expiry() is None


# ---------------------------------------------------------------------------
# Service accounts
# ---------------------------------------------------------------------------


def test_service_account_is_detected():
    claims = KeycloakClaims.from_payload(
        {"preferred_username": f"{SERVICE_ACCOUNT_PREFIX}de-client"}
    )
    assert claims.is_service_account is True


@pytest.mark.parametrize(
    "username",
    ["alice", "", "svc-account-x", "user-service-account-x"],
)
def test_ordinary_usernames_are_not_service_accounts(username):
    """Only the *prefix* counts — not the substring."""
    claims = KeycloakClaims.from_payload({"preferred_username": username})
    assert claims.is_service_account is False


# ---------------------------------------------------------------------------
# Presentation claims
# ---------------------------------------------------------------------------


def test_display_name_prefers_name():
    claims = KeycloakClaims.from_payload(
        {"name": "Alice Smith", "given_name": "A", "family_name": "S"}
    )
    assert claims.display_name() == "Alice Smith"


def test_display_name_falls_back_to_given_and_family():
    claims = KeycloakClaims.from_payload({"given_name": "Alice", "family_name": "Smith"})
    assert claims.display_name() == "Alice Smith"


def test_display_name_tolerates_a_single_part():
    assert KeycloakClaims.from_payload({"given_name": "Alice"}).display_name() == "Alice"


def test_display_name_is_empty_when_absent():
    assert KeycloakClaims.from_payload({}).display_name() == ""


def test_expiry_is_an_aware_utc_datetime():
    claims = KeycloakClaims.from_payload({"exp": 1900000000})
    assert claims.expiry() == datetime.fromtimestamp(1900000000, tz=UTC)


def test_raw_payload_is_preserved():
    """Unmodelled claims stay reachable without widening the model."""
    claims = KeycloakClaims.from_payload({"sub": "x", "realm_access": {"roles": ["a"]}})
    assert claims.raw["realm_access"] == {"roles": ["a"]}


# ---------------------------------------------------------------------------
# The trusted-decode header path
#
# ``extract_from_headers`` is exported public API with no call site in the
# server today, but an operator fronting mesa-mcp with an authenticating
# proxy can route through it. It must apply the same identity rules as the
# OIDC verifier, so it is tested rather than left to drift.
# ---------------------------------------------------------------------------


def _bearer(payload: dict) -> dict[str, str]:
    """Sign a token for the trusted-decode path.

    The signature is never checked there (verification is the OIDC
    verifier's job), so the key is arbitrary — but it is long enough to
    avoid PyJWT's short-key warning cluttering the suite.
    """
    import jwt

    token = jwt.encode(payload, "x" * 32, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_header_path_rejects_service_accounts():
    from mesa_mcp.auth.extract import extract_from_headers
    from mesa_mcp.config import Config

    headers = _bearer({"preferred_username": f"{SERVICE_ACCOUNT_PREFIX}de-client"})
    with pytest.raises(ValueError, match="service account"):
        extract_from_headers(headers, Config())


def test_header_path_accepts_a_user_and_strips_the_realm():
    from mesa_mcp.auth.extract import extract_from_headers
    from mesa_mcp.config import Config

    value = extract_from_headers(_bearer({"preferred_username": "alice@CyVerse"}), Config())
    assert value.username == "alice"


def test_header_path_falls_back_to_sub():
    from mesa_mcp.auth.extract import extract_from_headers
    from mesa_mcp.config import Config

    value = extract_from_headers(_bearer({"preferred_username": "", "sub": "uuid-9"}), Config())
    assert value.username == "uuid-9"
