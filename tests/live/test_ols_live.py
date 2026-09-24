"""Live pings of the OBO Foundry / EMBL-EBI OLS APIs through the MCP tools.

No LLM involved: these verify the upstream services answer and that the
``mesa_ols_*`` tools still parse what they return. Run with ``MESA_LIVE=1``.
"""

from __future__ import annotations

import httpx
import pytest

from mesa_mcp.errors import ToolError
from mesa_mcp.server import MesaServer

BIOME_IRI = "http://purl.obolibrary.org/obo/ENVO_00000428"
BIOME_CURIE = "ENVO:00000428"

pytestmark = pytest.mark.live


async def test_list_ontologies(ols_server: MesaServer) -> None:
    result = await ols_server.call("mesa_ols_list_ontologies", {"page": 0, "size": 5})
    assert len(result["ontologies"]) == 5
    # OLS4 indexes ~280 ontologies; anything far below means a broken page.
    assert result["totalElements"] > 200
    assert all("ontologyId" in o for o in result["ontologies"])


async def test_get_ontology_envo(ols_server: MesaServer) -> None:
    result = await ols_server.call("mesa_ols_get_ontology", {"ontology_id": "envo"})
    assert result["ontologyId"] == "envo"
    assert "environment" in result["title"].lower()


async def test_search_terms_biome_in_envo(ols_server: MesaServer) -> None:
    result = await ols_server.call(
        "mesa_ols_search_terms", {"query": "biome", "ontology_id": "envo", "size": 10}
    )
    assert result["count"] > 0
    assert BIOME_CURIE in {t["curie"] for t in result["results"]}


async def test_search_terms_across_ontologies(ols_server: MesaServer) -> None:
    result = await ols_server.call("mesa_ols_search_terms", {"query": "soil", "size": 10})
    assert result["count"] > 0
    assert all(t["ontologyId"] for t in result["results"])


async def test_get_term_biome(ols_server: MesaServer) -> None:
    term = await ols_server.call(
        "mesa_ols_get_term", {"ontology_id": "envo", "iri": BIOME_IRI}
    )
    assert term["label"] == "biome"
    assert term["curie"] == BIOME_CURIE
    assert term["iri"] == BIOME_IRI


async def test_get_term_unknown_iri_is_not_found(ols_server: MesaServer) -> None:
    with pytest.raises(ToolError) as exc_info:
        await ols_server.call(
            "mesa_ols_get_term",
            {"ontology_id": "envo", "iri": "http://purl.obolibrary.org/obo/ENVO_99999999"},
        )
    assert exc_info.value.code in {"not_found", "upstream_error"}


async def test_get_term_hierarchy_biome(ols_server: MesaServer) -> None:
    result = await ols_server.call(
        "mesa_ols_get_term_hierarchy",
        {"ontology_id": "envo", "iri": BIOME_IRI, "size": 20},
    )
    assert result["parentIri"] == BIOME_IRI
    assert result["count"] > 0
    assert all(child["iri"].startswith("http") for child in result["children"])


async def test_generate_template_envo(ols_server: MesaServer) -> None:
    result = await ols_server.call("mesa_ols_generate_template", {"ontology_id": "envo"})
    assert result["ontologyId"] == "envo"
    assert result["fields"], "template should expose at least one root-term field"
    field = result["fields"][0]
    assert {"key", "label", "curie", "iri"} <= set(field)


async def test_obo_foundry_registry_agrees_with_ols(ols_server: MesaServer) -> None:
    """Cross-check: the OBO Foundry registry lists ENVO under the same PURL base."""
    resp = httpx.get(
        "https://obofoundry.org/registry/ontologies.jsonld",
        timeout=30.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    entries = {o["id"]: o for o in resp.json()["ontologies"]}
    assert "envo" in entries
    assert entries["envo"].get("activity_status") == "active"

    term = await ols_server.call(
        "mesa_ols_get_term", {"ontology_id": "envo", "iri": BIOME_IRI}
    )
    assert term["iri"].startswith("http://purl.obolibrary.org/obo/ENVO_")
