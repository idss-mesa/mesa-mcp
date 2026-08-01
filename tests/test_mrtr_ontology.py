"""Multi Round-Trip Requests for ontology term disambiguation.

MRTR (MCP 2026-07-28) lets ``mesa_avu_apply_term`` ask *which* term the
user meant instead of failing when neither ``iri`` nor ``curie`` was
supplied.

The stateless core has no session to park a continuation in, so
``requestState`` travels out to the client and back. These tests pin the
consequences of that:

* the continuation carries only the question — no path, no identity;
* a term the server never offered is refused on resume, so editing the
  blob cannot steer the write;
* access is decided from the caller's live credentials on both legs.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import mesa_mcp.ols.tools.avu_apply_term as apply_term
from mesa_mcp.auth.models import AuthValue
from mesa_mcp.config import Config
from mesa_mcp.context import current_auth_value, current_config
from mesa_mcp.errors import InputRequired, ToolError
from mesa_mcp.server import _decode_request_state, _encode_request_state

BIOME_IRI = "http://purl.obolibrary.org/obo/ENVO_00000428"
OTHER_IRI = "http://purl.obolibrary.org/obo/ENVO_01000339"


@pytest.fixture
def auth() -> AuthValue:
    # A distinctive username: the leak assertion below is a substring
    # check, so a one-letter name would match incidentally (e.g. inside
    # "curie") and pass for the wrong reason.
    return AuthValue(
        username="zz-leak-canary-zz", zone="z", password=None, auth_scheme="native"
    )


@pytest.fixture(autouse=True)
def _bound_context(auth):
    config_token = current_config.set(Config())
    auth_token = current_auth_value.set(auth)
    yield
    current_auth_value.reset(auth_token)
    current_config.reset(config_token)


@pytest.fixture
def ols() -> MagicMock:
    client = MagicMock()
    client.search_terms.return_value = [
        {
            "iri": BIOME_IRI,
            "curie": "ENVO:00000428",
            "label": "biome",
            "description": "a major class of ecosystem",
        },
        {
            "iri": OTHER_IRI,
            "curie": "ENVO:01000339",
            "label": "biome-like entity",
            "description": "something else",
        },
    ]
    return client


@pytest.fixture
def args(auth):
    return apply_term.ApplyTermInput(
        path=auth.accessible_paths()[0], ontology_id="envo", value="biome"
    )


def _irods_mocked():
    """Patch the iRODS write path; these tests are about the MRTR flow."""
    return (
        patch.object(apply_term, "default_pool"),
        patch.object(apply_term, "resolve_path_target", return_value="collection"),
        patch.object(
            apply_term,
            "add_avu_to_irods",
            return_value={
                "attribute": "envo.biome",
                "value": "biome",
                "unit": "ENVO:00000428",
            },
        ),
        patch.object(apply_term, "record_avu_change", new=AsyncMock(return_value=None)),
    )


async def _apply(args, auth, ols, elicited: dict[str, Any] | None = None):
    pool, resolve, add, record = _irods_mocked()
    with pool as pool_mock, resolve, add, record:
        pool_mock.return_value.get.return_value = MagicMock()
        return await apply_term.handle_mesa_avu_apply_term(
            args, auth_value=auth, client=ols, elicited=elicited
        )


# ---------------------------------------------------------------------------
# Round 1 — the question
# ---------------------------------------------------------------------------


async def test_ambiguous_term_elicits_a_choice(args, auth, ols):
    with pytest.raises(InputRequired) as exc_info:
        await _apply(args, auth, ols)
    pending = exc_info.value
    assert pending.key == "term_choice"
    assert pending.schema["$schema"].endswith("2020-12/schema")
    assert pending.schema["properties"]["iri"]["enum"] == [BIOME_IRI, OTHER_IRI]


async def test_continuation_carries_no_path_or_identity(args, auth, ols):
    """The blob is client-controlled; nothing privileged may ride in it."""
    with pytest.raises(InputRequired) as exc_info:
        await _apply(args, auth, ols)
    state = exc_info.value.state
    assert set(state) == {"tool", "ontology_id", "candidates"}
    blob = repr(state)
    assert auth.username not in blob
    assert args.path not in blob


async def test_no_candidates_falls_back_to_the_plain_error(args, auth, ols):
    ols.search_terms.return_value = []
    with pytest.raises(ToolError) as exc_info:
        await _apply(args, auth, ols)
    assert exc_info.value.code == "invalid_argument"


async def test_ols_outage_does_not_produce_a_broken_prompt(args, auth, ols):
    from mesa_mcp.ols.client import OLSAPIError

    ols.search_terms.side_effect = OLSAPIError("upstream down")
    with pytest.raises(ToolError):
        await _apply(args, auth, ols)


# ---------------------------------------------------------------------------
# Round 2 — the answer
# ---------------------------------------------------------------------------


async def test_chosen_term_is_applied_on_resume(args, auth, ols):
    with pytest.raises(InputRequired) as exc_info:
        await _apply(args, auth, ols)
    state = _decode_request_state(_encode_request_state(exc_info.value.state))

    result = await _apply(
        args,
        auth,
        ols,
        elicited={
            "responses": {
                "term_choice": {"action": "accept", "content": {"iri": BIOME_IRI}}
            },
            "state": state,
        },
    )
    assert result["term"]["curie"] == "ENVO:00000428"
    assert result["avu"]["unit"] == "ENVO:00000428"


async def test_a_term_never_offered_is_refused(args, auth, ols):
    """Editing the round-tripped blob must not steer the write."""
    with pytest.raises(InputRequired) as exc_info:
        await _apply(args, auth, ols)
    state = _decode_request_state(_encode_request_state(exc_info.value.state))

    with pytest.raises(ToolError) as err:
        await _apply(
            args,
            auth,
            ols,
            elicited={
                "responses": {
                    "term_choice": {
                        "action": "accept",
                        "content": {"iri": "http://evil.example/TERM_1"},
                    }
                },
                "state": state,
            },
        )
    assert err.value.code == "invalid_argument"
    assert "not among the offered" in err.value.message


async def test_decline_writes_nothing(args, auth, ols):
    with pytest.raises(ToolError) as err:
        await _apply(
            args,
            auth,
            ols,
            elicited={
                "responses": {"term_choice": {"action": "decline", "content": None}},
                "state": {},
            },
        )
    assert "cancelled" in err.value.message.lower()


# ---------------------------------------------------------------------------
# Back-compatibility
# ---------------------------------------------------------------------------


async def test_explicit_term_never_elicits(auth, ols):
    """Existing clients that pass a curie are completely unaffected."""
    args = apply_term.ApplyTermInput(
        path=auth.accessible_paths()[0],
        ontology_id="envo",
        value="biome",
        curie="ENVO:00000428",
        label="biome",
    )
    result = await _apply(args, auth, ols)
    assert result["avu"]["attribute"] == "envo.biome"
    assert ols.search_terms.call_count == 0


# ---------------------------------------------------------------------------
# The continuation codec
# ---------------------------------------------------------------------------


def test_request_state_round_trips():
    state = {"tool": "t", "candidates": [{"iri": BIOME_IRI}]}
    assert _decode_request_state(_encode_request_state(state)) == state


def test_malformed_request_state_is_rejected():
    with pytest.raises(ToolError) as err:
        _decode_request_state("not-valid-base64-!!!")
    assert err.value.code == "invalid_argument"


def test_non_object_request_state_is_rejected():
    import base64

    encoded = base64.urlsafe_b64encode(b"[1,2,3]").decode()
    with pytest.raises(ToolError):
        _decode_request_state(encoded)


def test_oversized_continuation_is_refused():
    from mesa_mcp.server import MAX_REQUEST_STATE_BYTES

    with pytest.raises(ToolError) as err:
        _encode_request_state({"blob": "x" * (MAX_REQUEST_STATE_BYTES + 1)})
    assert err.value.code == "internal_error"
