"""Tests for the ``mesa_ols_*`` and ``mesa_avu_*`` MCP tools.

Each test drives the tool through :meth:`MesaServer.call`, which is the same
code path the MCP SDK adapter uses. The OLS client is swapped out for a
:class:`unittest.mock.MagicMock` via ``set_default_client`` so no network
traffic is generated.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from mesa_mcp.config import Config
from mesa_mcp.errors import ToolError
from mesa_mcp.ols import set_default_client
from mesa_mcp.ols.client import OLSAPIError
from mesa_mcp.server import MesaServer, get_tool


@pytest.fixture
def fake_client() -> Iterator[MagicMock]:
    """A mock OLS client wired in as the module-level singleton."""
    mock = MagicMock(name="OLSClient")
    set_default_client(mock)
    try:
        yield mock
    finally:
        set_default_client(None)


@pytest.fixture
def server() -> MesaServer:
    return MesaServer(config=Config())


# ---------------------------------------------------------------------------
# Registration sanity
# ---------------------------------------------------------------------------


class TestRegistration:
    @pytest.mark.parametrize(
        "tool_name",
        [
            "mesa_ols_list_ontologies",
            "mesa_ols_get_ontology",
            "mesa_ols_search_terms",
            "mesa_ols_get_term",
            "mesa_ols_get_term_hierarchy",
            "mesa_ols_generate_template",
            "mesa_avu_from_term",
        ],
    )
    def test_tool_is_registered(self, tool_name: str) -> None:
        spec = get_tool(tool_name)
        assert spec.name == tool_name
        assert spec.input_model is not None


# ---------------------------------------------------------------------------
# mesa_ols_list_ontologies
# ---------------------------------------------------------------------------


class TestListOntologiesTool:
    async def test_returns_catalog(self, server: MesaServer, fake_client: MagicMock) -> None:
        fake_client.list_ontologies.return_value = {
            "ontologies": [{"ontologyId": "envo"}],
            "totalElements": 1,
            "page": 0,
            "size": 25,
        }
        result = await server.call("mesa_ols_list_ontologies", {"page": 0, "size": 25})
        fake_client.list_ontologies.assert_called_once_with(page=0, size=25)
        assert result["ontologies"][0]["ontologyId"] == "envo"


# ---------------------------------------------------------------------------
# mesa_ols_get_ontology
# ---------------------------------------------------------------------------


class TestGetOntologyTool:
    async def test_returns_record(self, server: MesaServer, fake_client: MagicMock) -> None:
        fake_client.get_ontology.return_value = {
            "ontologyId": "envo",
            "title": "Environment Ontology",
            "numberOfTerms": 6500,
        }
        result = await server.call("mesa_ols_get_ontology", {"ontology_id": "envo"})
        fake_client.get_ontology.assert_called_once_with("envo")
        assert result["title"] == "Environment Ontology"

    async def test_404_becomes_not_found(self, server: MesaServer, fake_client: MagicMock) -> None:
        fake_client.get_ontology.side_effect = OLSAPIError("missing", status_code=404)
        with pytest.raises(ToolError) as exc:
            await server.call("mesa_ols_get_ontology", {"ontology_id": "nope"})
        assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# mesa_ols_search_terms
# ---------------------------------------------------------------------------


class TestSearchTermsTool:
    async def test_scoped_search(self, server: MesaServer, fake_client: MagicMock) -> None:
        fake_client.search_terms.return_value = [
            {"label": "biome", "curie": "ENVO:00000428"},
        ]
        result = await server.call(
            "mesa_ols_search_terms",
            {"query": "biome", "ontology_id": "envo", "size": 5},
        )
        fake_client.search_terms.assert_called_once_with(
            query="biome", ontology_id="envo", size=5
        )
        assert result["count"] == 1
        assert result["results"][0]["label"] == "biome"

    async def test_descendants_branch(self, server: MesaServer, fake_client: MagicMock) -> None:
        fake_client.search_term_descendants.return_value = [{"label": "tropical biome"}]
        result = await server.call(
            "mesa_ols_search_terms",
            {
                "query": "tropical",
                "ontology_id": "envo",
                "descendants_of": "http://example.com/biome",
                "size": 10,
            },
        )
        fake_client.search_term_descendants.assert_called_once()
        assert result["count"] == 1
        # The unscoped search path must not have been hit.
        fake_client.search_terms.assert_not_called()


# ---------------------------------------------------------------------------
# mesa_ols_get_term
# ---------------------------------------------------------------------------


class TestGetTermTool:
    async def test_returns_term(self, server: MesaServer, fake_client: MagicMock) -> None:
        fake_client.get_term.return_value = {
            "label": "biome",
            "iri": "http://example.com/biome",
            "curie": "ENVO:00000428",
        }
        result = await server.call(
            "mesa_ols_get_term",
            {"ontology_id": "envo", "iri": "http://example.com/biome"},
        )
        fake_client.get_term.assert_called_once_with("envo", "http://example.com/biome")
        assert result["label"] == "biome"

    async def test_missing_term_raises(self, server: MesaServer, fake_client: MagicMock) -> None:
        fake_client.get_term.return_value = None
        with pytest.raises(ToolError) as exc:
            await server.call(
                "mesa_ols_get_term",
                {"ontology_id": "envo", "iri": "http://example.com/missing"},
            )
        assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# mesa_ols_get_term_hierarchy
# ---------------------------------------------------------------------------


class TestGetTermHierarchyTool:
    async def test_returns_children(self, server: MesaServer, fake_client: MagicMock) -> None:
        fake_client.get_term_children.return_value = [
            {"label": "tropical biome", "curie": "ENVO:01"},
        ]
        result = await server.call(
            "mesa_ols_get_term_hierarchy",
            {"ontology_id": "envo", "iri": "http://example.com/biome", "size": 5},
        )
        fake_client.get_term_children.assert_called_once_with(
            ontology_id="envo",
            iri="http://example.com/biome",
            size=5,
        )
        assert result["count"] == 1
        assert result["children"][0]["label"] == "tropical biome"
        assert result["ontologyId"] == "envo"
        assert result["parentIri"] == "http://example.com/biome"


# ---------------------------------------------------------------------------
# mesa_ols_generate_template
# ---------------------------------------------------------------------------


class TestGenerateTemplateTool:
    async def test_returns_template(self, server: MesaServer, fake_client: MagicMock) -> None:
        fake_client.generate_template.return_value = {
            "label": "Environment Ontology",
            "prefix": "envo.",
            "ontologyId": "envo",
            "fields": [
                {"key": "envo.biome", "label": "biome", "curie": "ENVO:00000428"},
            ],
        }
        result = await server.call(
            "mesa_ols_generate_template", {"ontology_id": "envo"}
        )
        fake_client.generate_template.assert_called_once_with("envo")
        assert result["prefix"] == "envo."
        assert result["fields"][0]["key"] == "envo.biome"


# ---------------------------------------------------------------------------
# mesa_avu_from_term
# ---------------------------------------------------------------------------


class TestAvuFromTermTool:
    async def test_full_lookup_path(self, server: MesaServer, fake_client: MagicMock) -> None:
        """When only the IRI is supplied, mesa_avu_from_term must look up the label."""
        fake_client.get_term.return_value = {
            "label": "biome",
            "iri": "http://purl.obolibrary.org/obo/ENVO_00000428",
            "curie": "ENVO:00000428",
        }
        result = await server.call(
            "mesa_avu_from_term",
            {
                "ontology_id": "envo",
                "value": "tropical forest",
                "iri": "http://purl.obolibrary.org/obo/ENVO_00000428",
            },
        )
        assert result["avu"] == {
            "attribute": "envo.biome",
            "value": "tropical forest",
            "unit": "ENVO:00000428",
        }
        assert result["term"]["ontologyId"] == "envo"
        assert result["term"]["label"] == "biome"
        assert result["term"]["curie"] == "ENVO:00000428"

    async def test_inline_label_and_curie_skips_lookup(
        self, server: MesaServer, fake_client: MagicMock
    ) -> None:
        """If the caller supplies label+curie, no OLS call is needed."""
        result = await server.call(
            "mesa_avu_from_term",
            {
                "ontology_id": "envo",
                "value": "forest",
                "label": "Environmental Feature",
                "curie": "ENVO:00002297",
            },
        )
        fake_client.get_term.assert_not_called()
        assert result["avu"]["attribute"] == "envo.environmental_feature"
        assert result["avu"]["unit"] == "ENVO:00002297"

    async def test_missing_iri_and_curie_raises(
        self, server: MesaServer, fake_client: MagicMock
    ) -> None:
        with pytest.raises(ToolError) as exc:
            await server.call(
                "mesa_avu_from_term",
                {"ontology_id": "envo", "value": "forest"},
            )
        assert exc.value.code == "invalid_argument"

    async def test_term_not_found_raises(
        self, server: MesaServer, fake_client: MagicMock
    ) -> None:
        fake_client.get_term.return_value = None
        with pytest.raises(ToolError) as exc:
            await server.call(
                "mesa_avu_from_term",
                {
                    "ontology_id": "envo",
                    "value": "forest",
                    "iri": "http://example.com/missing",
                },
            )
        assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# mesa_avu_apply_term is registered — exhaustive tests live in
# tests/test_mesa_avu_apply_term.py.
# ---------------------------------------------------------------------------


class TestApplyTermRegistration:
    def test_apply_term_is_registered(self) -> None:
        spec = get_tool("mesa_avu_apply_term")
        assert spec.name == "mesa_avu_apply_term"
        assert spec.input_model is not None
