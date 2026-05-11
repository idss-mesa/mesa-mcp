"""Tests for :mod:`mesa_mcp.ols.transform`.

These mirror the ``esiil-portal/tests/test_ols_transform.py`` cases, stripped
of Django setup. The whole point of porting these functions verbatim is that
AVUs written by mesa-mcp must round-trip through esiil-portal's reader — so
the assertions below are deliberately exact-equality on the AVU shape.
"""

from __future__ import annotations

from mesa_mcp.ols.client import _label_to_snake
from mesa_mcp.ols.transform import (
    avus_to_ontology_annotations,
    detect_ontology_prefixes,
    extract_ontology_avus,
    ontology_annotations_to_avus,
)

# ---------------------------------------------------------------------------
# ontology_annotations_to_avus
# ---------------------------------------------------------------------------


class TestAnnotationsToAvus:
    def test_basic_conversion(self):
        annotations = [
            {"key": "biome", "value": "tropical moist broadleaf forest", "curie": "ENVO:00000428"},
            {"key": "habitat", "value": "freshwater", "curie": "ENVO:00002011"},
        ]
        avus = ontology_annotations_to_avus("envo", annotations)
        assert len(avus) == 2
        assert avus[0] == {
            "attribute": "envo.biome",
            "value": "tropical moist broadleaf forest",
            "unit": "ENVO:00000428",
        }
        assert avus[1]["attribute"] == "envo.habitat"

    def test_empty_value_skipped(self):
        annotations = [
            {"key": "biome", "value": "", "curie": "ENVO:00000428"},
            {"key": "habitat", "value": "freshwater", "curie": ""},
        ]
        avus = ontology_annotations_to_avus("envo", annotations)
        assert len(avus) == 1
        assert avus[0]["attribute"] == "envo.habitat"

    def test_empty_key_skipped(self):
        annotations = [{"key": "", "value": "test", "curie": ""}]
        avus = ontology_annotations_to_avus("envo", annotations)
        assert len(avus) == 0

    def test_missing_curie_uses_empty(self):
        annotations = [{"key": "biome", "value": "forest"}]
        avus = ontology_annotations_to_avus("envo", annotations)
        assert avus[0]["unit"] == ""

    def test_prefix_lowercased(self):
        annotations = [{"key": "biome", "value": "forest", "curie": "ENVO:001"}]
        avus = ontology_annotations_to_avus("ENVO", annotations)
        assert avus[0]["attribute"] == "envo.biome"


# ---------------------------------------------------------------------------
# avus_to_ontology_annotations
# ---------------------------------------------------------------------------


class TestAvusToAnnotations:
    def test_roundtrip(self):
        """Regression: porting must not break the round-trip contract.

        This is the load-bearing test — the AVU shape contract in CLAUDE.md
        requires that mesa-mcp-written AVUs read identically to those written
        by esiil-portal.
        """
        original = [
            {"key": "biome", "value": "tropical forest", "curie": "ENVO:00000428"},
        ]
        avus = ontology_annotations_to_avus("envo", original)
        annotations = avus_to_ontology_annotations("envo", avus)
        assert len(annotations) == 1
        assert annotations[0]["key"] == "biome"
        assert annotations[0]["value"] == "tropical forest"
        assert annotations[0]["curie"] == "ENVO:00000428"

    def test_roundtrip_multiple_ontologies(self):
        """Cross-ontology AVUs round-trip independently — no bleed."""
        envo_in = [{"key": "biome", "value": "forest", "curie": "ENVO:001"}]
        go_in = [{"key": "cell", "value": "neuron", "curie": "GO:001"}]
        all_avus = ontology_annotations_to_avus("envo", envo_in) + ontology_annotations_to_avus(
            "go", go_in
        )

        envo_out = avus_to_ontology_annotations("envo", all_avus)
        go_out = avus_to_ontology_annotations("go", all_avus)

        assert envo_out == envo_in
        assert go_out == go_in

    def test_filters_by_prefix(self):
        avus = [
            {"attribute": "envo.biome", "value": "forest", "unit": "ENVO:001"},
            {"attribute": "go.cell", "value": "neuron", "unit": "GO:001"},
            {"attribute": "datacite.title", "value": "My Dataset", "unit": ""},
        ]
        annotations = avus_to_ontology_annotations("envo", avus)
        assert len(annotations) == 1
        assert annotations[0]["key"] == "biome"

    def test_case_insensitive(self):
        avus = [{"attribute": "ENVO.biome", "value": "forest", "unit": "ENVO:001"}]
        annotations = avus_to_ontology_annotations("envo", avus)
        assert len(annotations) == 1


# ---------------------------------------------------------------------------
# extract_ontology_avus
# ---------------------------------------------------------------------------


class TestExtractOntologyAvus:
    def test_filters_correctly(self):
        avus = [
            {"attribute": "envo.biome", "value": "forest", "unit": ""},
            {"attribute": "envo.habitat", "value": "lake", "unit": ""},
            {"attribute": "go.cell", "value": "neuron", "unit": ""},
        ]
        result = extract_ontology_avus(avus, "envo")
        assert len(result) == 2
        assert all(a["attribute"].startswith("envo.") for a in result)


# ---------------------------------------------------------------------------
# detect_ontology_prefixes
# ---------------------------------------------------------------------------


class TestDetectOntologyPrefixes:
    def test_detect_mixed_avus(self):
        avus = [
            {"attribute": "envo.biome", "value": "forest", "unit": ""},
            {"attribute": "envo.habitat", "value": "lake", "unit": ""},
            {"attribute": "go.cell", "value": "neuron", "unit": ""},
            {"attribute": "datacite.title", "value": "Test", "unit": ""},
            {"attribute": "dc.creator", "value": "Jane", "unit": ""},
            {"attribute": "eml.abstract", "value": "Summary", "unit": ""},
            {"attribute": "ipc-uuid", "value": "abc", "unit": ""},
        ]
        result = detect_ontology_prefixes(avus)
        ids = {r["ontologyId"] for r in result}
        assert "envo" in ids
        assert "go" in ids
        # Reserved prefixes should not appear.
        assert "datacite" not in ids
        assert "dc" not in ids
        assert "eml" not in ids

    def test_counts_correct(self):
        avus = [
            {"attribute": "envo.biome", "value": "a", "unit": ""},
            {"attribute": "envo.habitat", "value": "b", "unit": ""},
            {"attribute": "envo.feature", "value": "c", "unit": ""},
            {"attribute": "go.cell", "value": "d", "unit": ""},
        ]
        result = detect_ontology_prefixes(avus)
        envo = next(r for r in result if r["ontologyId"] == "envo")
        go = next(r for r in result if r["ontologyId"] == "go")
        assert envo["count"] == 3
        assert go["count"] == 1

    def test_sorted_by_count_desc(self):
        avus = [
            {"attribute": "go.cell", "value": "a", "unit": ""},
            {"attribute": "envo.biome", "value": "b", "unit": ""},
            {"attribute": "envo.habitat", "value": "c", "unit": ""},
        ]
        result = detect_ontology_prefixes(avus)
        assert result[0]["ontologyId"] == "envo"
        assert result[1]["ontologyId"] == "go"

    def test_with_known_ontology_ids(self):
        avus = [
            {"attribute": "envo.biome", "value": "a", "unit": ""},
            {"attribute": "go.cell", "value": "b", "unit": ""},
            {"attribute": "custom.field", "value": "c", "unit": ""},
        ]
        result = detect_ontology_prefixes(avus, known_ontology_ids={"envo", "go"})
        ids = {r["ontologyId"] for r in result}
        assert "envo" in ids
        assert "go" in ids
        assert "custom" not in ids

    def test_empty_avus(self):
        result = detect_ontology_prefixes([])
        assert result == []

    def test_no_dots_in_attribute(self):
        avus = [{"attribute": "simpletag", "value": "test", "unit": ""}]
        result = detect_ontology_prefixes(avus)
        assert result == []

    def test_system_prefixes_excluded(self):
        avus = [
            {"attribute": "ipc-uuid.something", "value": "a", "unit": ""},
            {"attribute": "irods::test.field", "value": "b", "unit": ""},
        ]
        result = detect_ontology_prefixes(avus)
        assert result == []


# ---------------------------------------------------------------------------
# Snake-case helper (lives in client.py because that's where the original did)
# ---------------------------------------------------------------------------


class TestLabelToSnake:
    def test_simple(self):
        assert _label_to_snake("Biome") == "biome"

    def test_multi_word(self):
        assert _label_to_snake("Environmental Feature") == "environmental_feature"

    def test_special_chars(self):
        # 'pH value' -> 'ph_value' (the '_to_snake_ helper strips punctuation
        # and collapses spaces; this is the contract esiil-portal relies on).
        assert _label_to_snake("pH value") == "ph_value"

    def test_empty(self):
        assert _label_to_snake("") == ""

    def test_hyphen_treated_as_punctuation(self):
        # Hyphens are stripped (the regex keeps only alphanumerics + spaces).
        assert _label_to_snake("foo-bar") == "foobar"

    def test_curie_to_iri_heuristic_is_label_only(self):
        # Sanity check: the snake helper does not look at CURIEs/IRIs; it is
        # strictly a label -> attribute-suffix transform.
        assert _label_to_snake("ENVO:00000428") == "envo00000428"


# ---------------------------------------------------------------------------
# Integration: snake-cased attribute names + full round-trip
# ---------------------------------------------------------------------------


class TestSnakeCasedRoundTrip:
    def test_snake_cased_attribute_matches_helper(self):
        """The attribute suffix in an AVU must equal ``_label_to_snake(label)``."""
        label = "Environmental Feature"
        snake = _label_to_snake(label)
        avus = ontology_annotations_to_avus(
            "envo", [{"key": snake, "value": "forest", "curie": "ENVO:00000111"}]
        )
        assert avus[0]["attribute"] == f"envo.{snake}"
        assert avus[0]["attribute"] == "envo.environmental_feature"

    def test_curie_lives_in_unit_not_attribute(self):
        """AVU shape contract: CURIE is the unit field, never embedded elsewhere."""
        avus = ontology_annotations_to_avus(
            "envo", [{"key": "biome", "value": "forest", "curie": "ENVO:00000428"}]
        )
        avu = avus[0]
        assert avu["unit"] == "ENVO:00000428"
        assert "ENVO:" not in avu["attribute"]
        assert "ENVO:" not in avu["value"]
