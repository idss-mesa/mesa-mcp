"""The local vLLM models drive the ``mesa_ols_*`` tools against live OLS.

Every model call goes through the :class:`TokenLedger` (see ``_llm.py``):
``max_tokens`` is clamped to the per-test / per-session budget, tool
results are truncated before they re-enter the prompt, and a usage table
is printed at the end of the run.

Requires ``MESA_LIVE=1`` and ``MESA_LLM_API_KEY`` (gateway reachable via
``scripts/llm_tunnel.sh up``).
"""

from __future__ import annotations

import math
import re

import pytest

from mesa_mcp.server import MesaServer

from ._llm import LiveSettings, LLMClient, TokenLedger, ToolAgent

pytestmark = [pytest.mark.live, pytest.mark.llm]

BIOME_IRI = "http://purl.obolibrary.org/obo/ENVO_00000428"
BIOME_CURIE = "ENVO:00000428"

SEARCH_TOOLS = ["mesa_ols_search_terms", "mesa_ols_get_term"]
ALL_OLS_TOOLS = [
    "mesa_ols_list_ontologies",
    "mesa_ols_get_ontology",
    "mesa_ols_search_terms",
    "mesa_ols_get_term",
    "mesa_ols_get_term_hierarchy",
]


# ---------------------------------------------------------------------------
# Gateway sanity
# ---------------------------------------------------------------------------


async def test_gateway_serves_configured_models(
    llm: LLMClient, live_settings: LiveSettings
) -> None:
    served = set(await llm.models())
    missing = {live_settings.agent_model, live_settings.fast_model} - served
    assert not missing, f"gateway at {live_settings.base_url} lacks {missing}; has {served}"


async def test_fast_model_answers_with_thinking_off(
    llm: LLMClient, live_settings: LiveSettings, token_ledger: TokenLedger
) -> None:
    result = await llm.chat(
        [{"role": "user", "content": "Reply with the single word: pong"}],
        model=live_settings.fast_model,
        max_tokens=16,
        think=False,
    )
    assert "pong" in result.content.lower()
    # Thinking off + a 16-token cap: the ledger must have seen a tiny bill.
    assert result.usage.completion_tokens <= 16
    assert token_ledger.spent_by_test(llm.test_id) == result.usage.total_tokens


# ---------------------------------------------------------------------------
# Agent: model → mesa_ols_* → live OLS → model
# ---------------------------------------------------------------------------


async def test_agent_finds_biome_curie(agent: ToolAgent) -> None:
    run = await agent.run(
        "Using the ENVO ontology, find the term whose label is exactly 'biome' "
        "and reply with its CURIE only.",
        tools=SEARCH_TOOLS,
    )
    searches = run.calls_to("mesa_ols_search_terms")
    assert searches, f"model never searched; final={run.final_text!r}"
    assert any(c.args.get("ontology_id", "").lower() == "envo" for c in searches)
    assert BIOME_CURIE in run.final_text, run.final_text


async def test_agent_grounds_iri_in_tool_output(agent: ToolAgent) -> None:
    """Whatever IRI the model reports must be one a tool actually returned."""
    run = await agent.run(
        "Search the ENVO ontology for a term describing 'forest soil' and reply "
        "with that term's full IRI only.",
        tools=SEARCH_TOOLS,
    )
    returned: set[str] = set()
    for result in run.results_for("mesa_ols_search_terms"):
        returned.update(t["iri"] for t in result.get("results", []))
    for result in run.results_for("mesa_ols_get_term"):
        if "iri" in result:
            returned.add(result["iri"])
    assert returned, "no term came back from OLS"
    reported = re.findall(r"https?://\S+", run.final_text)
    assert reported, f"no IRI in final answer: {run.final_text!r}"
    assert reported[0].rstrip(".,)") in returned, (
        f"model reported {reported[0]} which no tool returned; "
        f"seen={sorted(returned)[:5]}…"
    )


async def test_agent_walks_hierarchy(agent: ToolAgent, ols_server: MesaServer) -> None:
    run = await agent.run(
        f"List three direct child terms of the ENVO term with IRI {BIOME_IRI}. "
        "Reply with their labels, comma-separated.",
        tools=["mesa_ols_get_term_hierarchy", "mesa_ols_get_term"],
    )
    hierarchy_calls = run.calls_to("mesa_ols_get_term_hierarchy")
    assert hierarchy_calls, f"model never walked the hierarchy; final={run.final_text!r}"
    labels = {
        child["label"].lower()
        for c in hierarchy_calls
        for child in c.result.get("children", [])
    }
    assert labels
    mentioned = [lbl for lbl in labels if lbl in run.final_text.lower()]
    assert len(mentioned) >= 2, f"final={run.final_text!r}; children={sorted(labels)[:10]}"


async def test_agent_discovers_ontology_from_catalog(agent: ToolAgent) -> None:
    run = await agent.run(
        "Which OBO ontology id should I use to annotate a dataset with environmental "
        "biome and habitat terms? Look it up rather than guessing, then reply with "
        "the ontology id only.",
        tools=ALL_OLS_TOOLS,
    )
    assert run.calls, f"model answered without any tool call: {run.final_text!r}"
    assert "envo" in run.final_text.lower(), run.final_text


# ---------------------------------------------------------------------------
# Fast model as a judge over live OLS output
# ---------------------------------------------------------------------------


async def test_fast_model_judges_live_term(
    llm: LLMClient, ols_server: MesaServer, live_settings: LiveSettings
) -> None:
    """The fast model sorts a live ENVO term into the right domain.

    Note the OLS ``description`` for ENVO:biome is an editor's note about
    successional dynamics, not the textbook definition, so the judge is
    asked a discriminative question (which of three domains) rather than
    an open yes/no about the prose.
    """
    term = await ols_server.call(
        "mesa_ols_get_term", {"ontology_id": "envo", "iri": BIOME_IRI}
    )
    result = await llm.chat(
        [
            {
                "role": "system",
                "content": (
                    "You classify ontology terms. Answer with exactly one word "
                    "from: chemistry, anatomy, environment."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Term label: {term['label']}\n"
                    f"Ontology: {term['ontologyId']}\n"
                    f"Note: {term['description'][:400]}\n"
                    "Which domain does this term belong to?"
                ),
            },
        ],
        model=live_settings.fast_model,
        max_tokens=8,
    )
    assert "environment" in result.content.strip().lower(), result.content


# ---------------------------------------------------------------------------
# Embeddings over live search results
# ---------------------------------------------------------------------------


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


async def test_embeddings_rank_exact_label_first(
    llm: LLMClient, ols_server: MesaServer
) -> None:
    search = await ols_server.call(
        "mesa_ols_search_terms", {"query": "biome", "ontology_id": "envo", "size": 8}
    )
    labels = [t["label"] for t in search["results"]]
    assert "biome" in labels
    vectors = await llm.embed(["biome", *labels])
    query, candidates = vectors[0], vectors[1:]
    ranked = sorted(zip(labels, candidates, strict=True), key=lambda lc: -_cosine(query, lc[1]))
    assert ranked[0][0] == "biome", [lbl for lbl, _ in ranked]


# ---------------------------------------------------------------------------
# The budget actually bites
# ---------------------------------------------------------------------------


async def test_completion_is_clamped_to_remaining_budget(
    llm: LLMClient, token_ledger: TokenLedger, live_settings: LiveSettings
) -> None:
    """Ask for far more than the per-test budget; the ledger must clamp it."""
    remaining_before = token_ledger.remaining_for(llm.test_id)
    result = await llm.chat(
        [{"role": "user", "content": "Count from 1 to 5, digits only."}],
        model=live_settings.fast_model,
        max_tokens=remaining_before * 10,
    )
    assert result.usage.completion_tokens <= remaining_before
    assert token_ledger.remaining_for(llm.test_id) < remaining_before
