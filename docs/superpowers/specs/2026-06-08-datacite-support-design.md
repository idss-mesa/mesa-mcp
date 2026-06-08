# DataCite (descriptive-metadata) support for mesa-mcp — design spec

- **Status:** Approved (design)
- **Date:** 2026-06-08
- **Scope:** mesa-mcp (new `datacite/` package + 3–4 tools); no mesa-ducklake change
- **Origin:** Evaluating mesa-mcp's DataCite output for the Alcock leaf-phenotyping collection against the
  official CyVerse Data Commons template exposed that mesa-mcp has first-class **ontology** metadata support
  (OLS/OBO) but **zero** support for descriptive-metadata **standards**. See the comparison that motivated
  this: it found the content was reproduced/enriched, but with no schema, no validation, no controlled
  vocabularies, no structured creators/contributors, no DOI/Identifier, and no DataCite-XML export.

## Problem

`datacite`, `dc`, `eml` are in `RESERVED_PREFIXES` (`src/mesa_mcp/ols/transform.py:27-35`) and are explicitly
**skipped** by OLS detection. So "create DataCite" today means writing ad-hoc key/value AVUs (`ds_add_avu(s)`)
with no schema awareness:

1. No knowledge of DataCite **mandatory** fields → cannot warn that the **DOI/Identifier is missing** (a
   required element).
2. No **controlled-vocabulary** enforcement (`resourceTypeGeneral`, `contributorType`, `relationType`,
   `dateType`, `descriptionType` are enums).
3. No **structured/linked** entities — flat AVUs can't bind a creator to its affiliation **and** ORCID, so
   they can't round-trip to valid DataCite XML.
4. No identifier/DOI handling; no **export** to DataCite 4.x XML/JSON.
5. No canonical naming convention or legacy crosswalk (we had to hand-write two naming sets for the Alcock
   collection).

## Design principle: mirror the OLS pattern for a *standard* instead of an *ontology*

| OLS/OBO (exists) | DataCite (to build) |
|---|---|
| `ols/client.py` resolves terms from EMBL-EBI | `datacite/schema.py` — DataCite 4.x fields + enums (static, no network) |
| `ols/transform.py:ontology_annotations_to_avus` | `datacite/transform.py:datacite_to_avus` / `avus_to_datacite` |
| `mesa_ols_generate_template` (ontology → form) | `mesa_datacite_template` (DataCite → required-field scaffold) |
| `mesa_avu_apply_term` (resolve+validate+write+mirror) | `mesa_avu_apply_datacite` (validate+bulk-write+mirror) |
| OLS term existence = validation | Pydantic model + enum validators = validation |
| — | `mesa_datacite_export` (AVUs → DataCite 4.x XML/JSON) |

**Reuses (no new infra):** `register_tool` (`server.py:58`, auto-import), `add_avu_to_irods`
(`irods/_avu_helpers.py:128`), the bulk `ds_add_avus` (`irods/tools/add_avus.py`) + batched
`record_avu_changes` (`ducklake/client.py:385`) so a whole record is one DuckLake snapshot, the
Pydantic + `ToolError` pattern, and the OLS template/transform code shape.

## Components

### `src/mesa_mcp/datacite/schema.py` — the standard, as code
- `DataCiteMetadata(BaseModel)`: DataCite 4.x fields; **mandatory** = Identifier, Creator, Title, Publisher,
  PublicationYear, ResourceType (required), rest optional.
- Structured sub-models: `Creator(name, nameType, affiliation, nameIdentifier)`,
  `Contributor(name, contributorType, affiliation)`, `Subject(value, subjectScheme)`, `Date(date, dateType)`,
  `RelatedIdentifier(value, relatedIdentifierType, relationType)`, `RightsItem(rights, rightsURI)`,
  `GeoLocation(...)`.
- Controlled-vocab `Enum`s from the DataCite schema: `ResourceTypeGeneral`, `ContributorType`,
  `RelationType`, `RelatedIdentifierType`, `DateType`, `DescriptionType`, `NameType`.
- `LEGACY_CROSSWALK: dict` — each kernel field ↔ CyVerse template name(s)
  (`resourceTypeGeneral→datacite.resourcetype`, `resourceType→ResourceType`, `subject→Subject`,
  `contributor→contributorName`, …).

### `src/mesa_mcp/datacite/transform.py` — record ⇄ AVUs
- `datacite_to_avus(record, naming) -> list[{attribute,value,unit}]`, `naming ∈ {canonical, cyverse_template, both}`.
  Canonical = `datacite.<kernelField>`, **indexed/nested** for repeatables + structured entities:
  `datacite.creator.1.name`, `datacite.creator.1.affiliation`, `datacite.creator.1.nameIdentifier`,
  `datacite.subject.1`, `datacite.relatedIdentifier.1.value`/`.relationType`. Preserves grouping flat AVUs lose.
- `avus_to_datacite(avus) -> DataCiteMetadata` (round-trip).
- DataCite tools operate on the model; they do **not** touch OLS prefix detection (keep `datacite` reserved
  for OLS so ontology detection is unaffected).

### Tools (auto-register via `@register_tool`, like `ols/tools/*`)
- `mesa_datacite_template` — return the field set (label, required?, vocab options, repeatable?, cyverse alias).
- `mesa_avu_apply_datacite` — validate (Pydantic + enums; reject missing-mandatory/bad-vocab with structured
  `ToolError`) → one bulk `ds_add_avus` → DuckLake mirror.
- `mesa_datacite_export` — read AVUs → `avus_to_datacite` → emit DataCite 4.x XML and/or JSON (pure read).
- *(optional)* `mesa_datacite_validate` — read AVUs → report missing-mandatory / invalid-vocab / unlinked
  entities without writing ("is this DOI-ready?").

## Validation
Mandatory-field + enum validation in the Pydantic model (`ToolError(code="datacite_invalid", details=…)`),
plus a completeness scorer (must/should/optional) surfaced by `mesa_datacite_validate`.

## Phased rollout (each phase shippable, TDD)
1. `schema.py` + `transform.py` + round-trip/validation tests (pure, no iRODS).
2. `mesa_datacite_template` + `mesa_avu_apply_datacite` + tests (mock iRODS like `tests/test_ds_add_avus.py`).
3. `mesa_datacite_export` (XML/JSON) + DataCite-XSD validation test.
4. Docs + canonical-naming/crosswalk note in `CLAUDE.md`/`docs/dev/`.

## Tests
- Round-trip `record → datacite_to_avus → avus_to_datacite == record` (canonical + cyverse_template).
- Validation: missing mandatory → `ToolError`; bad `resourceTypeGeneral`/`relationType` → `ToolError`.
- Export: emitted XML validates against the DataCite 4.x XSD.
- Crosswalk: every CyVerse template field maps to/from a kernel field.

## Generalization
Put `schema.py`/`transform.py` behind a small `MetadataStandard` interface so the same machinery later serves
Dublin Core, schema.org, DCAT, EML (all in `RESERVED_PREFIXES` today) — giving mesa-mcp a symmetric surface:
ontology metadata via OLS **and** descriptive metadata via standard plugins, both validated, exportable, and
DuckLake-versioned.
