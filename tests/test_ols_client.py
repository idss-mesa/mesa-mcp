"""Tests for :class:`mesa_mcp.ols.client.OLSClient`.

Adapted from ``esiil-portal/tests/test_ols_client.py``. We stub
``client.session.get`` rather than ``requests.get`` directly so the per-instance
retry-mounted Session is exercised. The TTL cache is bypassed by constructing a
fresh ``OLSClient`` for each test — no Django cache flush needed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import requests as req

from mesa_mcp.ols.client import (
    OLSAPIError,
    OLSClient,
    _extract_ontologies,
    _extract_term,
    _label_to_snake,
    _truncate,
    get_ols_client,
)

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> OLSClient:
    return OLSClient(base_url="https://test.ols.example.com/api/v2")


def make_response(status_code: int = 200, json_data: dict[str, Any] | None = None, text: str = ""):
    """Build a duck-typed Response stand-in compatible with the client's needs."""

    class _Resp:
        def __init__(self) -> None:
            self.status_code = status_code
            self.ok = 200 <= status_code < 300
            self.text = text or json.dumps(json_data or {})
            self._payload = json_data or {}

        def json(self) -> dict[str, Any]:
            return self._payload

        def raise_for_status(self) -> None:
            if not self.ok:
                raise req.exceptions.HTTPError(f"{status_code} error")

    return _Resp()


# ---------------------------------------------------------------------------
# OLSClient init
# ---------------------------------------------------------------------------


class TestOLSClientInit:
    def test_init_sets_base_url(self, client: OLSClient) -> None:
        assert client.base_url == "https://test.ols.example.com/api/v2"

    def test_init_default_timeout(self, client: OLSClient) -> None:
        assert client.timeout == 15

    def test_no_auth_headers(self, client: OLSClient) -> None:
        assert client.session.auth is None
        assert "Authorization" not in client.session.headers

    def test_accept_json(self, client: OLSClient) -> None:
        assert client.session.headers.get("Accept") == "application/json"

    def test_caches_are_instantiated(self, client: OLSClient) -> None:
        # Each TTL cache should exist and be empty on a fresh client.
        for cache_name in (
            "_cache_catalog",
            "_cache_ontology",
            "_cache_search",
            "_cache_term",
            "_cache_children",
            "_cache_desc_search",
            "_cache_template",
        ):
            assert len(getattr(client, cache_name)) == 0


# ---------------------------------------------------------------------------
# list_ontologies
# ---------------------------------------------------------------------------


class TestListOntologies:
    def test_list_ontologies_success(self, client: OLSClient, mocker) -> None:
        api_response = {
            "elements": [
                {
                    "ontologyId": "envo",
                    "config": {
                        "title": "Environment Ontology",
                        "description": "An ontology of environments",
                    },
                    "numberOfTerms": 6500,
                    "status": "LOADED",
                },
                {
                    "ontologyId": "go",
                    "config": {"title": "Gene Ontology", "description": "GO"},
                    "numberOfTerms": 45000,
                    "status": "LOADED",
                },
            ],
            "totalElements": 266,
            "page": 0,
            "size": 25,
        }
        get_spy = mocker.patch.object(
            client.session, "get", return_value=make_response(200, api_response)
        )
        result = client.list_ontologies(page=0, size=25)

        # URL + params landed correctly.
        called_url, called_kwargs = get_spy.call_args.args[0], get_spy.call_args.kwargs
        assert called_url == "https://test.ols.example.com/api/v2/ontologies"
        assert called_kwargs["params"] == {"page": 0, "size": 25}

        # Headers (set on the session, not per-call) include Accept: application/json.
        assert client.session.headers.get("Accept") == "application/json"

        assert len(result["ontologies"]) == 2
        assert result["ontologies"][0]["ontologyId"] == "envo"
        assert result["ontologies"][0]["title"] == "Environment Ontology"
        assert result["totalElements"] == 266

    def test_list_ontologies_cached(self, client: OLSClient, mocker) -> None:
        # Pre-warm the cache. The second call should not hit the session at all.
        cached_data = {
            "ontologies": [{"ontologyId": "envo"}],
            "totalElements": 1,
            "page": 0,
            "size": 25,
        }
        client._cache_catalog["ols:catalog:0:25"] = cached_data
        get_spy = mocker.patch.object(client.session, "get")

        result = client.list_ontologies()
        assert result == cached_data
        get_spy.assert_not_called()


# ---------------------------------------------------------------------------
# get_ontology
# ---------------------------------------------------------------------------


class TestGetOntology:
    def test_get_ontology_success(self, client: OLSClient, mocker) -> None:
        api_response = {
            "ontologyId": "envo",
            "config": {
                "title": "Environment Ontology",
                "description": "An ontology of environments",
                "homepage": "https://github.com/EnvironmentOntology/envo",
                "version": "2024-01-01",
                "preferredPrefix": "ENVO",
            },
            "numberOfTerms": 6500,
            "numberOfProperties": 100,
            "numberOfIndividuals": 0,
            "status": "LOADED",
        }
        get_spy = mocker.patch.object(
            client.session, "get", return_value=make_response(200, api_response)
        )
        result = client.get_ontology("envo")

        assert get_spy.call_args.args[0] == "https://test.ols.example.com/api/v2/ontologies/envo"
        assert result["ontologyId"] == "envo"
        assert result["title"] == "Environment Ontology"
        assert result["numberOfTerms"] == 6500
        assert result["preferredPrefix"] == "ENVO"


# ---------------------------------------------------------------------------
# search_terms
# ---------------------------------------------------------------------------


class TestSearchTerms:
    def test_search_terms_success(self, client: OLSClient, mocker) -> None:
        api_response = {
            "elements": [
                {
                    "label": "biome",
                    "iri": "http://purl.obolibrary.org/obo/ENVO_00000428",
                    "curie": "ENVO:00000428",
                    "description": ["A biome is an ecosystem"],
                    "ontologyId": "envo",
                    "isRoot": False,
                    "hasChildren": True,
                },
            ],
        }
        get_spy = mocker.patch.object(
            client.session, "get", return_value=make_response(200, api_response)
        )
        results = client.search_terms("biome", ontology_id="envo")

        # Scoped search must include ontologyId and must NOT restrict to class
        # (registries like ROR rely on individuals being searchable).
        params = get_spy.call_args.kwargs["params"]
        assert params["search"] == "biome"
        assert params["ontologyId"] == "envo"
        assert params.get("type") != "class"

        assert len(results) == 1
        assert results[0]["label"] == "biome"
        assert results[0]["curie"] == "ENVO:00000428"
        assert results[0]["description"] == "A biome is an ecosystem"

    def test_search_terms_unscoped_restricts_to_class(self, client: OLSClient, mocker) -> None:
        get_spy = mocker.patch.object(
            client.session, "get", return_value=make_response(200, {"elements": []})
        )
        client.search_terms("biome")
        params = get_spy.call_args.kwargs["params"]
        assert params["type"] == "class"

    def test_search_terms_no_results(self, client: OLSClient, mocker) -> None:
        mocker.patch.object(
            client.session, "get", return_value=make_response(200, {"elements": []})
        )
        results = client.search_terms("zzzzzznonexistent")
        assert results == []


# ---------------------------------------------------------------------------
# get_term
# ---------------------------------------------------------------------------


class TestGetTerm:
    def test_get_term_success(self, client: OLSClient, mocker) -> None:
        iri = "http://purl.obolibrary.org/obo/ENVO_00000428"
        api_response = {
            "label": ["biome"],
            "iri": iri,
            "curie": "ENVO:00000428",
            "definition": [{"value": "A biome is an ecosystem."}],
            "ontologyId": "envo",
            "hasDirectChildren": True,
            "hasDirectParents": True,
        }
        get_spy = mocker.patch.object(
            client.session, "get", return_value=make_response(200, api_response)
        )
        result = client.get_term("envo", iri)

        # OLS4 v2 double-URL-encodes the IRI in the path; verify that.
        called_url = get_spy.call_args.args[0]
        assert "/ontologies/envo/classes/" in called_url
        # http://... must be double-encoded — '/' becomes '%252F', ':' becomes '%253A'.
        assert "%252F" in called_url
        assert "%253A" in called_url
        # The full undecoded IRI substring must not appear verbatim.
        assert "http://purl" not in called_url

        assert result is not None
        assert result["label"] == "biome"
        assert result["description"] == "A biome is an ecosystem."

    def test_get_term_404_returns_none(self, client: OLSClient, mocker) -> None:
        mocker.patch.object(
            client.session,
            "get",
            return_value=make_response(404, {"message": "Not found"}),
        )
        assert client.get_term("envo", "http://example.com/missing") is None


# ---------------------------------------------------------------------------
# get_term_children
# ---------------------------------------------------------------------------


class TestGetTermChildren:
    def test_returns_children(self, client: OLSClient, mocker) -> None:
        api_response = {
            "elements": [
                {
                    "label": "tropical biome",
                    "iri": "http://example.com/tropical",
                    "curie": "ENVO:01",
                    "ontologyId": "envo",
                },
            ],
        }
        get_spy = mocker.patch.object(
            client.session, "get", return_value=make_response(200, api_response)
        )
        result = client.get_term_children(
            "envo", "http://purl.obolibrary.org/obo/ENVO_00000428", size=50
        )

        assert get_spy.call_args.kwargs["params"] == {"size": 50}
        assert len(result) == 1
        assert result[0]["label"] == "tropical biome"

    def test_404_returns_empty(self, client: OLSClient, mocker) -> None:
        mocker.patch.object(
            client.session, "get", return_value=make_response(404, {"message": "Not found"})
        )
        result = client.get_term_children("envo", "http://example.com/missing")
        assert result == []


# ---------------------------------------------------------------------------
# search_term_descendants
# ---------------------------------------------------------------------------


class TestSearchTermDescendants:
    def test_uses_v1_search_endpoint(self, client: OLSClient, mocker) -> None:
        api_response = {
            "response": {
                "docs": [
                    {
                        "label": "tropical biome",
                        "iri": "http://example.com/t",
                        "obo_id": "ENVO:01",
                        "ontology_name": "envo",
                    },
                ],
            },
        }
        get_spy = mocker.patch.object(
            client.session, "get", return_value=make_response(200, api_response)
        )
        results = client.search_term_descendants(
            "tropical", "envo", "http://purl.obolibrary.org/obo/ENVO_00000428"
        )

        # Hits the v1-compat search URL, not the v2 path.
        called_url = get_spy.call_args.args[0]
        assert called_url == "https://www.ebi.ac.uk/ols4/api/search"
        params = get_spy.call_args.kwargs["params"]
        assert params["q"] == "tropical"
        assert params["ontology"] == "envo"
        assert params["allChildrenOf"] == "http://purl.obolibrary.org/obo/ENVO_00000428"

        assert len(results) == 1
        assert results[0]["label"] == "tropical biome"
        assert results[0]["curie"] == "ENVO:01"


# ---------------------------------------------------------------------------
# generate_template
# ---------------------------------------------------------------------------


class TestGenerateTemplate:
    def test_generate_template(self, client: OLSClient, mocker) -> None:
        ontology_resp = {
            "ontologyId": "envo",
            "config": {"title": "Environment Ontology", "description": "Envs"},
            "numberOfTerms": 6500,
            "status": "LOADED",
        }
        roots_resp = {
            "elements": [
                {
                    "label": "biome",
                    "iri": "http://purl.obolibrary.org/obo/ENVO_00000428",
                    "curie": "ENVO:00000428",
                    "description": ["A biome"],
                    "ontologyId": "envo",
                    "isRoot": True,
                    "hasChildren": True,
                },
                {
                    "label": "environmental feature",
                    "iri": "http://purl.obolibrary.org/obo/ENVO_00002297",
                    "curie": "ENVO:00002297",
                    "description": [],
                    "ontologyId": "envo",
                    "isRoot": True,
                    "hasChildren": True,
                },
            ],
        }

        def fake_get(url: str, **kwargs: Any):
            if "/classes" in url:
                return make_response(200, roots_resp)
            return make_response(200, ontology_resp)

        mocker.patch.object(client.session, "get", side_effect=fake_get)
        template = client.generate_template("envo")

        assert template["label"] == "Environment Ontology"
        assert template["prefix"] == "envo."
        assert template["ontologyId"] == "envo"
        assert len(template["fields"]) == 2
        assert template["fields"][0]["key"] == "envo.biome"
        assert template["fields"][0]["curie"] == "ENVO:00000428"
        assert template["fields"][1]["key"] == "envo.environmental_feature"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_api_error_status(self, client: OLSClient, mocker) -> None:
        mocker.patch.object(
            client.session,
            "get",
            return_value=make_response(404, {"message": "Not found"}),
        )
        with pytest.raises(OLSAPIError) as exc:
            client._make_request("/ontologies/nonexistent")
        assert exc.value.status_code == 404

    def test_timeout_error(self, client: OLSClient, mocker) -> None:
        mocker.patch.object(client.session, "get", side_effect=req.exceptions.Timeout())
        with pytest.raises(OLSAPIError, match="timed out"):
            client._make_request("/ontologies")

    def test_connection_error(self, client: OLSClient, mocker) -> None:
        mocker.patch.object(
            client.session, "get", side_effect=req.exceptions.ConnectionError("refused")
        )
        with pytest.raises(OLSAPIError, match="Connection error"):
            client._make_request("/ontologies")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_label_to_snake_simple(self) -> None:
        assert _label_to_snake("Biome") == "biome"

    def test_label_to_snake_multi_word(self) -> None:
        assert _label_to_snake("Environmental Feature") == "environmental_feature"

    def test_label_to_snake_special_chars(self) -> None:
        assert _label_to_snake("pH value") == "ph_value"

    def test_label_to_snake_empty(self) -> None:
        assert _label_to_snake("") == ""

    def test_truncate_short(self) -> None:
        assert _truncate("hello", 10) == "hello"

    def test_truncate_long(self) -> None:
        assert _truncate("a very long description", 10) == "a very lo…"

    def test_truncate_empty(self) -> None:
        assert _truncate("", 10) == ""

    def test_extract_ontologies(self) -> None:
        data = {
            "elements": [
                {
                    "ontologyId": "go",
                    "config": {"title": "Gene Ontology", "description": "GO terms"},
                    "numberOfTerms": 45000,
                    "status": "LOADED",
                }
            ]
        }
        result = _extract_ontologies(data)
        assert len(result) == 1
        assert result[0]["ontologyId"] == "go"
        assert result[0]["title"] == "Gene Ontology"

    def test_extract_term_with_list_description(self) -> None:
        data = {
            "label": "cell",
            "iri": "http://example.com/cell",
            "curie": "GO:0005623",
            "description": ["The basic structural unit"],
            "ontologyId": "go",
            "isRoot": False,
            "hasChildren": True,
        }
        result = _extract_term(data)
        assert result["label"] == "cell"
        assert result["description"] == "The basic structural unit"

    def test_extract_term_with_string_description(self) -> None:
        data = {
            "label": "cell",
            "iri": "http://example.com/cell",
            "description": "A cell",
            "ontologyId": "go",
        }
        result = _extract_term(data)
        assert result["description"] == "A cell"

    def test_extract_term_v2_format(self) -> None:
        data = {
            "label": ["biome"],
            "iri": "http://purl.obolibrary.org/obo/ENVO_00000428",
            "curie": "ENVO:00000428",
            "definition": [{"type": ["reification"], "value": "A biome is an ecosystem."}],
            "ontologyId": "envo",
            "hasDirectChildren": True,
            "hasDirectParents": True,
        }
        result = _extract_term(data)
        assert result["label"] == "biome"
        assert result["description"] == "A biome is an ecosystem."
        assert result["hasChildren"] is True
        assert result["isRoot"] is False

    def test_extract_term_v2_root(self) -> None:
        data = {
            "label": ["entity"],
            "iri": "http://example.com/entity",
            "curie": "BFO:0000001",
            "hasDirectParents": False,
            "hasDirectChildren": True,
        }
        result = _extract_term(data)
        assert result["isRoot"] is True


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestFactory:
    def test_get_ols_client_returns_client(self) -> None:
        c = get_ols_client()
        assert isinstance(c, OLSClient)
        assert "ebi.ac.uk" in c.base_url
