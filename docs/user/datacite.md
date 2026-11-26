---
type: Guide
title: DataCite metadata
description: Write, check, and export DataCite 4.x descriptive metadata as iRODS AVUs with the four mesa_datacite_* and mesa_avu_apply_datacite tools, including the AVU naming scheme and how to produce DataCite XML for a DOI request.
tags:
  - datacite
  - doi
  - avu
  - metadata
generated:
  by: "claude/opus-5.5"
  at: "2026-11-24T00:00:00Z"
sources:
  - id: datacite-pkg
    resource: "https://github.com/idss-mesa/mesa-mcp/tree/main/src/mesa_mcp/datacite"
    title: "mesa-mcp datacite package (schema, transform, export, tools)"
    author: "team:idss-mesa"
  - id: design
    resource: "https://github.com/idss-mesa/mesa-mcp/blob/main/docs/design/2026-06-08-datacite-support-design.md"
    title: "DataCite support design record"
    author: "team:idss-mesa"
  - id: datacite-schema
    resource: "https://schema.datacite.org/meta/kernel-4/"
    title: "DataCite Metadata Schema 4.x"
    author: "team:datacite"
status: stable
stale_after: "2027-05-24T00:00:00Z"
---

# DataCite metadata

What this page covers: how to record a dataset's descriptive metadata in
the [DataCite 4.x](https://schema.datacite.org/meta/kernel-4/) kernel as
iRODS AVUs, check that the record is complete enough for a DOI, and export
it as DataCite XML or JSON. Four tools do this; they never call DataCite
itself and do not register DOIs.

| Tool | Reads or writes iRODS? | What it does |
| --- | --- | --- |
| `mesa_datacite_template` | No | Returns the field scaffold: each field, whether it is mandatory or repeatable, its controlled vocabulary, and its canonical AVU key. |
| `mesa_avu_apply_datacite` | Writes | Validates a DataCite record and writes it to a path as AVUs, then mirrors all of them to the AVU history as one snapshot. |
| `mesa_datacite_validate` | No | Checks a list of AVUs for the mandatory fields and valid vocabulary values; reports `doi_ready`. |
| `mesa_datacite_export` | No | Rebuilds the record from a list of AVUs and returns DataCite kernel-4 XML or DataCite REST JSON. |

## AVU naming

DataCite AVUs always have an empty `unit`. Two naming schemes exist.

**Canonical** (what export and validate read):

- Scalars are `datacite.<field>`: `datacite.identifier`,
  `datacite.identifierType`, `datacite.publisher`,
  `datacite.publicationYear`, `datacite.resourceTypeGeneral`,
  `datacite.resourceType`, `datacite.language`, `datacite.version`.
- Repeatable or structured fields are indexed from 1 with sub-fields:
  `datacite.title.1.value`, `datacite.creator.1.name`,
  `datacite.creator.1.affiliation`, `datacite.creator.1.nameIdentifier`,
  `datacite.subject.1.value`, `datacite.relatedIdentifier.1.relationType`,
  `datacite.format.1`, `datacite.size.1`, and so on. The index keeps a
  creator's name, affiliation and ORCID together, which flat AVUs cannot.

**CyVerse template** (the column names of CyVerse's DOI-request
template): `datacite.title`, `datacite.creator`, `datacite.publisher`,
`datacite.publicationyear`, `datacite.resourcetype`, `Identifier`,
`identifierType`, `creatorAffiliation`, `ResourceType`, `Subject`,
`Rights`, `Description`, and similar. Only the first title, creator,
rights and description are written in this form. `LEGACY_CROSSWALK` in
`src/mesa_mcp/datacite/schema.py` maps these names to kernel fields.

`mesa_avu_apply_datacite` takes `naming` = `canonical`,
`cyverse_template` or `both` (the default). `both` writes the union,
skipping duplicate attribute/value pairs.

## Mandatory fields

A record is DOI-ready when it has all six kernel fields: `identifier`,
`title`, `creator`, `publisher`, `publicationYear` (a 4-digit year) and
`resourceTypeGeneral` (one of DataCite's controlled values, such as
`Dataset`). Call `mesa_datacite_template` to get the vocabularies for
`resourceTypeGeneral`, `contributorType`, `descriptionType` and
`relationType`.

## Write a record

```json
{
  "tool": "mesa_avu_apply_datacite",
  "input": {
    "target": "/iplant/home/alice/proj/leaf-images",
    "naming": "canonical",
    "record": {
      "identifier": "10.1234/example",
      "titles": ["Leaf phenotype images, 2026 field season"],
      "creators": [{"name": "Doe, Jane", "affiliation": "Example University"}],
      "publisher": "CyVerse Data Commons",
      "publicationYear": 2026,
      "resourceTypeGeneral": "Dataset"
    }
  }
}
```

The record is validated before anything is written. A bad record fails
with `datacite_invalid` and the Pydantic errors in `details`. On success
the result reports `written` (the count), any per-AVU `errors`, and a
`partial_failure` with code `ducklake_mirror_failed` if the history mirror
failed after the iRODS writes. The path must be inside your accessible
paths (home or shared).

## Check and export a record

`mesa_datacite_validate` and `mesa_datacite_export` take a list of AVUs,
**not a path**. They do not read iRODS. To export what is on a dataset:

1. Read the AVUs with `ds_list_avus` (`target_type: "path"`) or
   `ds_get_metadata`.
2. Pass on the `datacite.*` AVUs. The record is rebuilt from the
   canonical names, so a path written with `naming: "canonical"` or
   `"both"` exports; one written only with `cyverse_template` names does
   not.
3. Check completeness:

    ```json
    {"tool": "mesa_datacite_validate", "input": {"avus": [ … ]}}
    ```

    The result is `{"doi_ready": true|false, "missing_mandatory": [...],
    "errors": [...]}`.

4. Export:

    ```json
    {"tool": "mesa_datacite_export", "input": {"avus": [ … ], "format": "xml"}}
    ```

    `format` is `xml` (the default; DataCite kernel-4 XML, namespace
    `http://datacite.org/schema/kernel-4`, the form a DOI registration
    takes) or `json` (DataCite REST JSON). The result is
    `{"format": …, "document": "<string>"}`. AVUs that cannot form a valid
    record fail with `datacite_incomplete`.

Submitting the XML to DataCite, or to CyVerse's DOI request process, is
outside mesa-mcp.

## History

Because `mesa_avu_apply_datacite` writes one snapshot per record, a
record's history in a MESA-enabled project can be read with
`mesa_ducklake_history`, filtered by attribute (for example
`attribute: "datacite.publisher"`). See
[Metadata workflows](examples.md#see-how-metadata-changed).

## See also

- [Tools reference](tools-reference.md#mesa_datacite_-datacite-descriptive-metadata)
- [DataCite support design record](../design/2026-06-08-datacite-support-design.md)
  for why the scheme looks like this.
