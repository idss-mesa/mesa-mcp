# DataCite Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give mesa-mcp first-class DataCite descriptive-metadata support — a validated DataCite 4.x model, a record⇄AVU transform with a canonical (and CyVerse-legacy) naming, and MCP tools to scaffold, validate, apply (bulk-write + DuckLake mirror), and export DataCite records.

**Architecture:** Mirror the existing OLS/OBO package shape (`src/mesa_mcp/ols/`) for a *standard* instead of an *ontology*: a static schema module, a pure transform module, an export module, and auto-registered tools that reuse the existing AVU-write plumbing (`ds_add_avus` + `record_avu_changes`). No mesa-ducklake change.

**Tech Stack:** Python 3.11, Pydantic v2 (already a dep), stdlib `xml.etree.ElementTree`, pytest. Tests run with `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest` from the `mesa-mcp/` repo root.

**Spec:** `docs/superpowers/specs/2026-06-08-datacite-support-design.md`

**Conventions for every command below:**
- `PY=/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python`
- Run all `pytest`/`ruff`/`mypy` from `/Users/tswetnam/Desktop/mesa-ai-test/mesa-mcp`
- Commit trailer (append to every commit message):
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/mesa_mcp/datacite/__init__.py` | package marker | Create |
| `src/mesa_mcp/datacite/schema.py` | DataCite 4.x enums + sub-models + `DataCiteMetadata` + `LEGACY_CROSSWALK` | Create |
| `src/mesa_mcp/datacite/transform.py` | `datacite_to_avus(record, naming)` + `avus_to_datacite(avus)` | Create |
| `src/mesa_mcp/datacite/export.py` | `datacite_to_xml(record)` + `datacite_to_json(record)` | Create |
| `src/mesa_mcp/datacite/tools/__init__.py` | pkgutil auto-import (mirror `irods/tools/__init__.py`) | Create |
| `src/mesa_mcp/datacite/tools/template.py` | `mesa_datacite_template` tool | Create |
| `src/mesa_mcp/datacite/tools/apply.py` | `mesa_avu_apply_datacite` tool | Create |
| `src/mesa_mcp/datacite/tools/validate.py` | `mesa_datacite_validate` tool | Create |
| `src/mesa_mcp/datacite/tools/export.py` | `mesa_datacite_export` tool | Create |
| `src/mesa_mcp/server.py` | register the new tools package (one import line) | Modify |
| `tests/test_datacite_schema.py` … `tests/test_datacite_tools.py` | tests | Create |

---

## Task 0: Branch + baseline

**Files:** none (git)

- [ ] **Step 1: Branch from main**
```bash
cd /Users/tswetnam/Desktop/mesa-ai-test/mesa-mcp
git checkout main && git checkout -b feat/datacite-support
```
- [ ] **Step 2: Baseline the suite**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest -q`
Expected: passes (the known pre-existing `test_ols_client.py` errors about a missing `mocker` fixture are unrelated; everything else green).

---

## Task 1: DataCite enums + structured sub-models (`schema.py`)

**Files:**
- Create: `src/mesa_mcp/datacite/__init__.py`, `src/mesa_mcp/datacite/schema.py`
- Test: `tests/test_datacite_schema.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_datacite_schema.py
import pytest
from pydantic import ValidationError
from mesa_mcp.datacite.schema import (
    Creator, Subject, ResourceTypeGeneral, DescriptionType, DataCiteMetadata,
)


def test_resource_type_general_enum_rejects_unknown():
    with pytest.raises(ValueError):
        ResourceTypeGeneral("NotAType")


def test_creator_requires_name():
    with pytest.raises(ValidationError):
        Creator()  # name is mandatory
    c = Creator(name="Alcock, Thomas", affiliation="University of Nottingham")
    assert c.name == "Alcock, Thomas"


def test_minimal_valid_record():
    rec = DataCiteMetadata(
        identifier="10.25739/xyz", identifierType="DOI",
        titles=["U.Nottm_2016_RIPRleaf_images"],
        creators=[Creator(name="Alcock, Thomas")],
        publisher="CyVerse Data Commons", publicationYear=2016,
        resourceTypeGeneral=ResourceTypeGeneral.Image, resourceType="leaf phenotyping",
    )
    assert rec.publicationYear == 2016
    assert rec.subjects == []


def test_missing_mandatory_field_raises():
    with pytest.raises(ValidationError):
        DataCiteMetadata(  # no creators
            identifier="10.25739/xyz", identifierType="DOI",
            titles=["t"], publisher="p", publicationYear=2016,
            resourceTypeGeneral=ResourceTypeGeneral.Dataset,
        )
```

- [ ] **Step 2: Run to verify it fails**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_schema.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mesa_mcp.datacite'`.

- [ ] **Step 3: Create the package + schema**
`src/mesa_mcp/datacite/__init__.py`:
```python
"""DataCite descriptive-metadata support (schema, transform, export, tools)."""
```
`src/mesa_mcp/datacite/schema.py`:
```python
"""DataCite Metadata Schema 4.x as Pydantic models + controlled-vocabulary enums.

Static and offline — no network. Mandatory fields (Identifier, Creator, Title,
Publisher, PublicationYear, ResourceType) are required by the model; everything
else is optional. Mirrors the role OLS plays for ontology metadata.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResourceTypeGeneral(str, Enum):
    Audiovisual = "Audiovisual"; Book = "Book"; BookChapter = "BookChapter"
    Collection = "Collection"; ComputationalNotebook = "ComputationalNotebook"
    ConferencePaper = "ConferencePaper"; ConferenceProceeding = "ConferenceProceeding"
    DataPaper = "DataPaper"; Dataset = "Dataset"; Dissertation = "Dissertation"
    Event = "Event"; Image = "Image"; InteractiveResource = "InteractiveResource"
    Journal = "Journal"; JournalArticle = "JournalArticle"; Model = "Model"
    OutputManagementPlan = "OutputManagementPlan"; PeerReview = "PeerReview"
    PhysicalObject = "PhysicalObject"; Preprint = "Preprint"; Report = "Report"
    Service = "Service"; Software = "Software"; Sound = "Sound"
    Standard = "Standard"; Text = "Text"; Workflow = "Workflow"; Other = "Other"


class ContributorType(str, Enum):
    ContactPerson = "ContactPerson"; DataCollector = "DataCollector"
    DataCurator = "DataCurator"; DataManager = "DataManager"; Distributor = "Distributor"
    Editor = "Editor"; HostingInstitution = "HostingInstitution"; Producer = "Producer"
    ProjectLeader = "ProjectLeader"; ProjectManager = "ProjectManager"
    ProjectMember = "ProjectMember"; RegistrationAgency = "RegistrationAgency"
    RegistrationAuthority = "RegistrationAuthority"; RelatedPerson = "RelatedPerson"
    Researcher = "Researcher"; ResearchGroup = "ResearchGroup"
    RightsHolder = "RightsHolder"; Sponsor = "Sponsor"; Supervisor = "Supervisor"
    WorkPackageLeader = "WorkPackageLeader"; Other = "Other"


class DateType(str, Enum):
    Accepted = "Accepted"; Available = "Available"; Copyrighted = "Copyrighted"
    Collected = "Collected"; Created = "Created"; Issued = "Issued"
    Submitted = "Submitted"; Updated = "Updated"; Valid = "Valid"; Withdrawn = "Withdrawn"


class DescriptionType(str, Enum):
    Abstract = "Abstract"; Methods = "Methods"; SeriesInformation = "SeriesInformation"
    TableOfContents = "TableOfContents"; TechnicalInfo = "TechnicalInfo"; Other = "Other"


class RelationType(str, Enum):
    IsCitedBy = "IsCitedBy"; Cites = "Cites"; IsSupplementTo = "IsSupplementTo"
    IsSupplementedBy = "IsSupplementedBy"; IsContinuedBy = "IsContinuedBy"
    Continues = "Continues"; IsDescribedBy = "IsDescribedBy"; Describes = "Describes"
    IsPartOf = "IsPartOf"; HasPart = "HasPart"; IsReferencedBy = "IsReferencedBy"
    References = "References"; IsDocumentedBy = "IsDocumentedBy"; Documents = "Documents"
    IsCompiledBy = "IsCompiledBy"; Compiles = "Compiles"; IsVariantFormOf = "IsVariantFormOf"
    IsDerivedFrom = "IsDerivedFrom"; IsSourceOf = "IsSourceOf"; IsVersionOf = "IsVersionOf"
    HasVersion = "HasVersion"; IsNewVersionOf = "IsNewVersionOf"; IsObsoletedBy = "IsObsoletedBy"


class RelatedIdentifierType(str, Enum):
    DOI = "DOI"; URL = "URL"; URN = "URN"; Handle = "Handle"; ARK = "ARK"
    ISBN = "ISBN"; ISSN = "ISSN"; PMID = "PMID"; arXiv = "arXiv"; bibcode = "bibcode"
    IGSN = "IGSN"; PURL = "PURL"; UPC = "UPC"; w3id = "w3id"; EAN13 = "EAN13"


class NameType(str, Enum):
    Personal = "Personal"; Organizational = "Organizational"


class Creator(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1)
    nameType: NameType | None = None
    affiliation: str | None = None
    nameIdentifier: str | None = None  # e.g. an ORCID
    nameIdentifierScheme: str | None = None


class Contributor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1)
    contributorType: ContributorType
    affiliation: str | None = None


class Subject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(..., min_length=1)
    subjectScheme: str | None = None


class DateInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str = Field(..., min_length=1)
    dateType: DateType


class RelatedIdentifier(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(..., min_length=1)
    relatedIdentifierType: RelatedIdentifierType
    relationType: RelationType


class Description(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(..., min_length=1)
    descriptionType: DescriptionType = DescriptionType.Abstract


class Rights(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(..., min_length=1)
    rightsURI: str | None = None


class GeoLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    place: str | None = None
    point: str | None = None
    box: str | None = None


class DataCiteMetadata(BaseModel):
    """A DataCite 4.x record. Mandatory kernel fields are required."""

    model_config = ConfigDict(extra="forbid")

    # --- mandatory ---
    identifier: str = Field(..., min_length=1)
    identifierType: str = "DOI"
    titles: list[str] = Field(..., min_length=1)
    creators: list[Creator] = Field(..., min_length=1)
    publisher: str = Field(..., min_length=1)
    publicationYear: int
    resourceTypeGeneral: ResourceTypeGeneral
    # --- recommended/optional ---
    resourceType: str | None = None
    subjects: list[Subject] = Field(default_factory=list)
    contributors: list[Contributor] = Field(default_factory=list)
    dates: list[DateInfo] = Field(default_factory=list)
    relatedIdentifiers: list[RelatedIdentifier] = Field(default_factory=list)
    descriptions: list[Description] = Field(default_factory=list)
    rightsList: list[Rights] = Field(default_factory=list)
    geoLocations: list[GeoLocation] = Field(default_factory=list)
    language: str | None = None
    formats: list[str] = Field(default_factory=list)
    sizes: list[str] = Field(default_factory=list)
    version: str | None = None

    @field_validator("publicationYear")
    @classmethod
    def _year_range(cls, v: int) -> int:
        if not (1000 <= v <= 9999):
            raise ValueError("publicationYear must be a 4-digit year")
        return v
```

- [ ] **Step 4: Run to verify it passes**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_schema.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**
```bash
git add src/mesa_mcp/datacite/__init__.py src/mesa_mcp/datacite/schema.py tests/test_datacite_schema.py
git commit -m "feat(datacite): DataCite 4.x Pydantic model + controlled-vocab enums

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Legacy CyVerse crosswalk (`schema.py`)

**Files:**
- Modify: `src/mesa_mcp/datacite/schema.py` (append `LEGACY_CROSSWALK`)
- Modify: `tests/test_datacite_schema.py` (append a test)

- [ ] **Step 1: Append the failing test**
```python
def test_legacy_crosswalk_covers_template_fields():
    from mesa_mcp.datacite.schema import LEGACY_CROSSWALK
    # Every CyVerse DOI-request CSV column maps to a kernel field.
    for col in ["datacite.title", "creatorAffiliation", "datacite.resourcetype",
                "ResourceType", "Subject", "contributorName", "identifierType",
                "Rights", "Description", "descriptionType", "compressed_data"]:
        assert col in LEGACY_CROSSWALK, f"missing crosswalk for {col}"
    assert LEGACY_CROSSWALK["datacite.resourcetype"] == "resourceTypeGeneral"
    assert LEGACY_CROSSWALK["ResourceType"] == "resourceType"
```

- [ ] **Step 2: Run to verify it fails**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_schema.py::test_legacy_crosswalk_covers_template_fields -q`
Expected: FAIL — `ImportError: cannot import name 'LEGACY_CROSSWALK'`.

- [ ] **Step 3: Append the crosswalk to `schema.py`**
```python
# CyVerse DOI-request template column name -> kernel field name.
LEGACY_CROSSWALK: dict[str, str] = {
    "datacite.title": "title",
    "datacite.creator": "creator",
    "creatorAffiliation": "affiliation",
    "creatorNameIdentifier": "nameIdentifier",
    "datacite.publisher": "publisher",
    "datacite.publicationyear": "publicationYear",
    "datacite.resourcetype": "resourceTypeGeneral",
    "ResourceType": "resourceType",
    "contributorName": "contributor",
    "contributorType": "contributorType",
    "Subject": "subject",
    "Identifier": "identifier",
    "identifierType": "identifierType",
    "AlternateIdentifier": "alternateIdentifier",
    "RelatedIdentifier": "relatedIdentifier",
    "relationType": "relationType",
    "Rights": "rights",
    "Description": "description",
    "descriptionType": "descriptionType",
    "compressed_data": "compressed",
    "geoLocationBox": "geoLocationBox",
    "geoLocationPlace": "geoLocationPlace",
    "geoLocationPoint": "geoLocationPoint",
}
```

- [ ] **Step 4: Run to verify it passes**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_schema.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**
```bash
git add src/mesa_mcp/datacite/schema.py tests/test_datacite_schema.py
git commit -m "feat(datacite): legacy CyVerse template crosswalk

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `datacite_to_avus` — canonical indexed naming (`transform.py`)

**Files:**
- Create: `src/mesa_mcp/datacite/transform.py`
- Test: `tests/test_datacite_transform.py`

Canonical naming: simple scalars → `datacite.<field>`; repeatable/structured → indexed with sub-fields,
e.g. `datacite.creator.1.name`, `datacite.creator.1.affiliation`, `datacite.subject.1.value`,
`datacite.relatedIdentifier.1.relationType`. AVUs are `{attribute, value, unit:""}`.

- [ ] **Step 1: Write the failing test**
```python
# tests/test_datacite_transform.py
from mesa_mcp.datacite.schema import (
    Creator, Subject, DataCiteMetadata, ResourceTypeGeneral,
)
from mesa_mcp.datacite.transform import datacite_to_avus


def _rec():
    return DataCiteMetadata(
        identifier="10.25739/xyz", identifierType="DOI",
        titles=["U.Nottm_2016_RIPRleaf_images"],
        creators=[Creator(name="Alcock, Thomas",
                          affiliation="University of Nottingham",
                          nameIdentifier="0000-0001-2345-6789")],
        publisher="CyVerse Data Commons", publicationYear=2016,
        resourceTypeGeneral=ResourceTypeGeneral.Image, resourceType="leaf phenotyping",
        subjects=[Subject(value="Brassica"), Subject(value="Phenotyping")],
        language="en",
    )


def test_canonical_avus_scalars_and_indexed():
    avus = datacite_to_avus(_rec(), naming="canonical")
    pairs = {(a["attribute"], a["value"]) for a in avus}
    assert ("datacite.identifier", "10.25739/xyz") in pairs
    assert ("datacite.publisher", "CyVerse Data Commons") in pairs
    assert ("datacite.publicationYear", "2016") in pairs
    assert ("datacite.resourceTypeGeneral", "Image") in pairs
    assert ("datacite.title.1.value", "U.Nottm_2016_RIPRleaf_images") in pairs
    assert ("datacite.creator.1.name", "Alcock, Thomas") in pairs
    assert ("datacite.creator.1.affiliation", "University of Nottingham") in pairs
    assert ("datacite.creator.1.nameIdentifier", "0000-0001-2345-6789") in pairs
    assert ("datacite.subject.1.value", "Brassica") in pairs
    assert ("datacite.subject.2.value", "Phenotyping") in pairs
    assert all(a["unit"] == "" for a in avus)
```

- [ ] **Step 2: Run to verify it fails**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_transform.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mesa_mcp.datacite.transform'`.

- [ ] **Step 3: Create `transform.py` (canonical only for now)**
```python
"""DataCite record <-> iRODS AVU triples.

Canonical naming: scalars -> ``datacite.<field>``; repeatable/structured entities
-> indexed with sub-fields (``datacite.creator.1.name`` ...). This preserves the
grouping that flat AVUs lose, so a record can round-trip to/from AVUs and to XML.
"""

from __future__ import annotations

from typing import Any

from mesa_mcp.datacite.schema import DataCiteMetadata

_Avu = dict[str, str]


def _avu(attribute: str, value: Any) -> _Avu:
    return {"attribute": attribute, "value": str(value), "unit": ""}


def _entity_avus(prefix: str, items: list[Any], fields: list[str]) -> list[_Avu]:
    """Serialize a list of sub-models as ``<prefix>.<i>.<field>`` (1-indexed)."""
    out: list[_Avu] = []
    for i, item in enumerate(items, start=1):
        data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        for f in fields:
            v = data.get(f)
            if v is not None and v != "":
                out.append(_avu(f"{prefix}.{i}.{f}", v))
    return out


def _canonical(rec: DataCiteMetadata) -> list[_Avu]:
    out: list[_Avu] = [
        _avu("datacite.identifier", rec.identifier),
        _avu("datacite.identifierType", rec.identifierType),
        _avu("datacite.publisher", rec.publisher),
        _avu("datacite.publicationYear", rec.publicationYear),
        _avu("datacite.resourceTypeGeneral", rec.resourceTypeGeneral.value),
    ]
    if rec.resourceType:
        out.append(_avu("datacite.resourceType", rec.resourceType))
    if rec.language:
        out.append(_avu("datacite.language", rec.language))
    if rec.version:
        out.append(_avu("datacite.version", rec.version))
    for i, t in enumerate(rec.titles, start=1):
        out.append(_avu(f"datacite.title.{i}.value", t))
    out += _entity_avus("datacite.creator", rec.creators,
                        ["name", "nameType", "affiliation", "nameIdentifier", "nameIdentifierScheme"])
    out += _entity_avus("datacite.contributor", rec.contributors,
                        ["name", "contributorType", "affiliation"])
    out += _entity_avus("datacite.subject", rec.subjects, ["value", "subjectScheme"])
    out += _entity_avus("datacite.date", rec.dates, ["date", "dateType"])
    out += _entity_avus("datacite.relatedIdentifier", rec.relatedIdentifiers,
                        ["value", "relatedIdentifierType", "relationType"])
    out += _entity_avus("datacite.description", rec.descriptions, ["value", "descriptionType"])
    out += _entity_avus("datacite.rights", rec.rightsList, ["value", "rightsURI"])
    out += _entity_avus("datacite.geoLocation", rec.geoLocations, ["place", "point", "box"])
    for i, fmt in enumerate(rec.formats, start=1):
        out.append(_avu(f"datacite.format.{i}", fmt))
    for i, sz in enumerate(rec.sizes, start=1):
        out.append(_avu(f"datacite.size.{i}", sz))
    return out


def datacite_to_avus(record: DataCiteMetadata, naming: str = "canonical") -> list[_Avu]:
    """Serialize a DataCite record to AVU triples.

    ``naming`` ∈ {``canonical``, ``cyverse_template``, ``both``}. (cyverse_template
    + both are added in Task 4.)
    """
    if naming == "canonical":
        return _canonical(record)
    raise ValueError(f"unsupported naming: {naming!r}")
```

- [ ] **Step 4: Run to verify it passes**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_transform.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**
```bash
git add src/mesa_mcp/datacite/transform.py tests/test_datacite_transform.py
git commit -m "feat(datacite): datacite_to_avus canonical indexed naming

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `cyverse_template` + `both` naming (`transform.py`)

**Files:**
- Modify: `src/mesa_mcp/datacite/transform.py`
- Modify: `tests/test_datacite_transform.py`

- [ ] **Step 1: Append the failing test**
```python
def test_cyverse_template_naming_joins_repeatables():
    avus = datacite_to_avus(_rec(), naming="cyverse_template")
    pairs = {(a["attribute"], a["value"]) for a in avus}
    assert ("datacite.title", "U.Nottm_2016_RIPRleaf_images") in pairs
    assert ("datacite.creator", "Alcock, Thomas") in pairs
    assert ("creatorAffiliation", "University of Nottingham") in pairs
    assert ("datacite.resourcetype", "Image") in pairs        # general -> legacy resourcetype
    assert ("ResourceType", "leaf phenotyping") in pairs
    assert ("Subject", "Brassica, Phenotyping") in pairs       # repeatables joined
    assert ("identifierType", "DOI") in pairs


def test_both_is_superset():
    a = {(x["attribute"], x["value"]) for x in datacite_to_avus(_rec(), naming="canonical")}
    b = {(x["attribute"], x["value"]) for x in datacite_to_avus(_rec(), naming="cyverse_template")}
    both = {(x["attribute"], x["value"]) for x in datacite_to_avus(_rec(), naming="both")}
    assert a <= both and b <= both
```

- [ ] **Step 2: Run to verify it fails**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_transform.py -q`
Expected: FAIL — `ValueError: unsupported naming: 'cyverse_template'`.

- [ ] **Step 3: Add the cyverse_template + both branches**
Add this function and extend `datacite_to_avus`:
```python
def _cyverse_template(rec: DataCiteMetadata) -> list[_Avu]:
    out: list[_Avu] = [
        _avu("datacite.title", rec.titles[0]),
        _avu("datacite.creator", rec.creators[0].name),
        _avu("datacite.publisher", rec.publisher),
        _avu("datacite.publicationyear", rec.publicationYear),
        _avu("datacite.resourcetype", rec.resourceTypeGeneral.value),
        _avu("identifierType", rec.identifierType),
    ]
    if rec.identifier:
        out.append(_avu("Identifier", rec.identifier))
    if rec.creators[0].affiliation:
        out.append(_avu("creatorAffiliation", rec.creators[0].affiliation))
    if rec.creators[0].nameIdentifier:
        out.append(_avu("creatorNameIdentifier", rec.creators[0].nameIdentifier))
    if rec.resourceType:
        out.append(_avu("ResourceType", rec.resourceType))
    if rec.subjects:
        out.append(_avu("Subject", ", ".join(s.value for s in rec.subjects)))
    if rec.contributors:
        out.append(_avu("contributorName", ", ".join(c.name for c in rec.contributors)))
    if rec.rightsList:
        out.append(_avu("Rights", rec.rightsList[0].value))
    if rec.descriptions:
        out.append(_avu("Description", rec.descriptions[0].value))
        out.append(_avu("descriptionType", rec.descriptions[0].descriptionType.value))
    for rel in rec.relatedIdentifiers:
        out.append(_avu("RelatedIdentifier", rel.value))
        out.append(_avu("relationType", rel.relationType.value))
    return out
```
Replace the body of `datacite_to_avus`:
```python
def datacite_to_avus(record: DataCiteMetadata, naming: str = "canonical") -> list[_Avu]:
    if naming == "canonical":
        return _canonical(record)
    if naming == "cyverse_template":
        return _cyverse_template(record)
    if naming == "both":
        seen: set[tuple[str, str]] = set()
        merged: list[_Avu] = []
        for a in _canonical(record) + _cyverse_template(record):
            key = (a["attribute"], a["value"])
            if key not in seen:
                seen.add(key)
                merged.append(a)
        return merged
    raise ValueError(f"unsupported naming: {naming!r}")
```

- [ ] **Step 4: Run to verify it passes**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_transform.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**
```bash
git add src/mesa_mcp/datacite/transform.py tests/test_datacite_transform.py
git commit -m "feat(datacite): cyverse_template + both naming modes

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `avus_to_datacite` round-trip (`transform.py`)

**Files:**
- Modify: `src/mesa_mcp/datacite/transform.py`
- Modify: `tests/test_datacite_transform.py`

- [ ] **Step 1: Append the failing test**
```python
def test_canonical_round_trip():
    from mesa_mcp.datacite.transform import avus_to_datacite
    rec = _rec()
    back = avus_to_datacite(datacite_to_avus(rec, naming="canonical"))
    assert back.identifier == rec.identifier
    assert back.titles == rec.titles
    assert back.publicationYear == rec.publicationYear
    assert back.resourceTypeGeneral == rec.resourceTypeGeneral
    assert [c.name for c in back.creators] == [c.name for c in rec.creators]
    assert back.creators[0].nameIdentifier == "0000-0001-2345-6789"
    assert [s.value for s in back.subjects] == ["Brassica", "Phenotyping"]
```

- [ ] **Step 2: Run to verify it fails**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_transform.py::test_canonical_round_trip -q`
Expected: FAIL — `ImportError: cannot import name 'avus_to_datacite'`.

- [ ] **Step 3: Add `avus_to_datacite` to `transform.py`**
```python
import re as _re

from mesa_mcp.datacite.schema import (
    Contributor, Creator, DataCiteMetadata, DateInfo, Description, GeoLocation,
    RelatedIdentifier, Rights, Subject,
)

_INDEXED = _re.compile(r"^datacite\.(\w+)\.(\d+)\.(\w+)$")

_ENTITY_MODELS = {
    "creator": Creator, "contributor": Contributor, "subject": Subject,
    "date": DateInfo, "relatedIdentifier": RelatedIdentifier,
    "description": Description, "rights": Rights, "geoLocation": GeoLocation,
}


def avus_to_datacite(avus: list[_Avu]) -> DataCiteMetadata:
    """Rebuild a DataCiteMetadata from canonical-naming AVUs."""
    scalars: dict[str, str] = {}
    titles: dict[int, str] = {}
    formats: dict[int, str] = {}
    sizes: dict[int, str] = {}
    entities: dict[str, dict[int, dict[str, str]]] = {k: {} for k in _ENTITY_MODELS}
    for a in avus:
        attr, val = a["attribute"], a["value"]
        m = _INDEXED.match(attr)
        if m:
            ent, idx, field = m.group(1), int(m.group(2)), m.group(3)
            if ent == "title" and field == "value":
                titles[idx] = val
            elif ent in entities:
                entities[ent].setdefault(idx, {})[field] = val
            continue
        m2 = _re.match(r"^datacite\.(format|size)\.(\d+)$", attr)
        if m2:
            (formats if m2.group(1) == "format" else sizes)[int(m2.group(2))] = val
            continue
        if attr.startswith("datacite."):
            scalars[attr[len("datacite."):]] = val

    def _ordered(d: dict[int, Any]) -> list[Any]:
        return [d[i] for i in sorted(d)]

    built: dict[str, list[Any]] = {}
    for ent, model in _ENTITY_MODELS.items():
        rows = [model(**entities[ent][i]) for i in sorted(entities[ent])]
        built[ent] = rows

    return DataCiteMetadata(
        identifier=scalars["identifier"],
        identifierType=scalars.get("identifierType", "DOI"),
        titles=_ordered(titles),
        creators=built["creator"],
        publisher=scalars["publisher"],
        publicationYear=int(scalars["publicationYear"]),
        resourceTypeGeneral=scalars["resourceTypeGeneral"],
        resourceType=scalars.get("resourceType"),
        language=scalars.get("language"),
        version=scalars.get("version"),
        subjects=built["subject"],
        contributors=built["contributor"],
        dates=built["date"],
        relatedIdentifiers=built["relatedIdentifier"],
        descriptions=built["description"],
        rightsList=built["rights"],
        geoLocations=built["geoLocation"],
        formats=_ordered(formats),
        sizes=_ordered(sizes),
    )
```

- [ ] **Step 4: Run to verify it passes**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_transform.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**
```bash
git add src/mesa_mcp/datacite/transform.py tests/test_datacite_transform.py
git commit -m "feat(datacite): avus_to_datacite round-trip

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: DataCite 4.x XML/JSON export (`export.py`)

**Files:**
- Create: `src/mesa_mcp/datacite/export.py`
- Test: `tests/test_datacite_export.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_datacite_export.py
import xml.etree.ElementTree as ET
from mesa_mcp.datacite.schema import Creator, DataCiteMetadata, ResourceTypeGeneral
from mesa_mcp.datacite.export import datacite_to_xml, datacite_to_json


def _rec():
    return DataCiteMetadata(
        identifier="10.25739/xyz", identifierType="DOI", titles=["T"],
        creators=[Creator(name="Alcock, Thomas", affiliation="U. Nottingham")],
        publisher="CyVerse Data Commons", publicationYear=2016,
        resourceTypeGeneral=ResourceTypeGeneral.Image, resourceType="leaf phenotyping",
    )


def test_xml_has_required_elements_and_parses():
    xml = datacite_to_xml(_rec())
    root = ET.fromstring(xml)
    ns = {"d": "http://datacite.org/schema/kernel-4"}
    assert root.find("d:identifier", ns).text == "10.25739/xyz"
    assert root.find("d:identifier", ns).get("identifierType") == "DOI"
    assert root.find("d:titles/d:title", ns).text == "T"
    assert root.find("d:creators/d:creator/d:creatorName", ns).text == "Alcock, Thomas"
    assert root.find("d:publisher", ns).text == "CyVerse Data Commons"
    assert root.find("d:publicationYear", ns).text == "2016"
    rt = root.find("d:resourceType", ns)
    assert rt.get("resourceTypeGeneral") == "Image" and rt.text == "leaf phenotyping"


def test_json_has_attributes_block():
    import json
    obj = json.loads(datacite_to_json(_rec()))
    assert obj["data"]["attributes"]["doi"] == "10.25739/xyz"
    assert obj["data"]["attributes"]["titles"][0]["title"] == "T"
```

- [ ] **Step 2: Run to verify it fails**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_export.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mesa_mcp.datacite.export'`.

- [ ] **Step 3: Create `export.py`**
```python
"""Emit a DataCite record as kernel-4 XML or DataCite REST JSON (no network)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from mesa_mcp.datacite.schema import DataCiteMetadata

_NS = "http://datacite.org/schema/kernel-4"


def datacite_to_xml(rec: DataCiteMetadata) -> str:
    ET.register_namespace("", _NS)
    root = ET.Element(f"{{{_NS}}}resource")
    ident = ET.SubElement(root, f"{{{_NS}}}identifier", identifierType=rec.identifierType)
    ident.text = rec.identifier
    creators = ET.SubElement(root, f"{{{_NS}}}creators")
    for c in rec.creators:
        ce = ET.SubElement(creators, f"{{{_NS}}}creator")
        ET.SubElement(ce, f"{{{_NS}}}creatorName").text = c.name
        if c.affiliation:
            ET.SubElement(ce, f"{{{_NS}}}affiliation").text = c.affiliation
        if c.nameIdentifier:
            ni = ET.SubElement(ce, f"{{{_NS}}}nameIdentifier",
                               nameIdentifierScheme=c.nameIdentifierScheme or "ORCID")
            ni.text = c.nameIdentifier
    titles = ET.SubElement(root, f"{{{_NS}}}titles")
    for t in rec.titles:
        ET.SubElement(titles, f"{{{_NS}}}title").text = t
    ET.SubElement(root, f"{{{_NS}}}publisher").text = rec.publisher
    ET.SubElement(root, f"{{{_NS}}}publicationYear").text = str(rec.publicationYear)
    rt = ET.SubElement(root, f"{{{_NS}}}resourceType",
                       resourceTypeGeneral=rec.resourceTypeGeneral.value)
    rt.text = rec.resourceType or ""
    if rec.subjects:
        subs = ET.SubElement(root, f"{{{_NS}}}subjects")
        for s in rec.subjects:
            el = ET.SubElement(subs, f"{{{_NS}}}subject")
            if s.subjectScheme:
                el.set("subjectScheme", s.subjectScheme)
            el.text = s.value
    if rec.contributors:
        cons = ET.SubElement(root, f"{{{_NS}}}contributors")
        for c in rec.contributors:
            ce = ET.SubElement(cons, f"{{{_NS}}}contributor", contributorType=c.contributorType.value)
            ET.SubElement(ce, f"{{{_NS}}}contributorName").text = c.name
    if rec.descriptions:
        des = ET.SubElement(root, f"{{{_NS}}}descriptions")
        for d in rec.descriptions:
            ET.SubElement(des, f"{{{_NS}}}description",
                          descriptionType=d.descriptionType.value).text = d.value
    if rec.rightsList:
        rl = ET.SubElement(root, f"{{{_NS}}}rightsList")
        for r in rec.rightsList:
            el = ET.SubElement(rl, f"{{{_NS}}}rights")
            if r.rightsURI:
                el.set("rightsURI", r.rightsURI)
            el.text = r.value
    return ET.tostring(root, encoding="unicode")


def datacite_to_json(rec: DataCiteMetadata) -> str:
    attrs = {
        "doi": rec.identifier,
        "titles": [{"title": t} for t in rec.titles],
        "creators": [
            {"name": c.name, **({"affiliation": [c.affiliation]} if c.affiliation else {}),
             **({"nameIdentifiers": [{"nameIdentifier": c.nameIdentifier,
                                      "nameIdentifierScheme": c.nameIdentifierScheme or "ORCID"}]}
                if c.nameIdentifier else {})}
            for c in rec.creators
        ],
        "publisher": rec.publisher,
        "publicationYear": rec.publicationYear,
        "types": {"resourceTypeGeneral": rec.resourceTypeGeneral.value,
                  **({"resourceType": rec.resourceType} if rec.resourceType else {})},
        "subjects": [{"subject": s.value} for s in rec.subjects],
        "descriptions": [{"description": d.value, "descriptionType": d.descriptionType.value}
                         for d in rec.descriptions],
    }
    return json.dumps({"data": {"type": "dois", "attributes": attrs}}, indent=2)
```

- [ ] **Step 4: Run to verify it passes**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_export.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**
```bash
git add src/mesa_mcp/datacite/export.py tests/test_datacite_export.py
git commit -m "feat(datacite): kernel-4 XML + REST JSON export

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Tools package + `mesa_datacite_template` + `mesa_datacite_validate`

**Files:**
- Create: `src/mesa_mcp/datacite/tools/__init__.py`, `src/mesa_mcp/datacite/tools/template.py`,
  `src/mesa_mcp/datacite/tools/validate.py`
- Modify: `src/mesa_mcp/server.py` (register the package)
- Test: `tests/test_datacite_tools.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_datacite_tools.py
import asyncio
from mesa_mcp.server import _REGISTRY


def test_datacite_tools_registered():
    for name in ("mesa_datacite_template", "mesa_datacite_validate"):
        assert name in _REGISTRY


def test_template_lists_mandatory_fields():
    from mesa_mcp.datacite.tools.template import handle_datacite_template, TemplateInput
    res = asyncio.run(handle_datacite_template(TemplateInput()))
    mandatory = {f["field"] for f in res["fields"] if f["required"]}
    assert {"identifier", "title", "creator", "publisher",
            "publicationYear", "resourceTypeGeneral"} <= mandatory


def test_validate_flags_missing_doi():
    from mesa_mcp.datacite.tools.validate import handle_datacite_validate, ValidateInput
    avus = [
        {"attribute": "datacite.title.1.value", "value": "T"},
        {"attribute": "datacite.creator.1.name", "value": "Alcock, Thomas"},
        {"attribute": "datacite.publisher", "value": "CyVerse"},
        {"attribute": "datacite.publicationYear", "value": "2016"},
        {"attribute": "datacite.resourceTypeGeneral", "value": "Image"},
    ]
    res = asyncio.run(handle_datacite_validate(ValidateInput(avus=avus)))
    assert res["doi_ready"] is False
    assert "identifier" in res["missing_mandatory"]
```

- [ ] **Step 2: Run to verify it fails**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_tools.py -q`
Expected: FAIL — registry missing the tools / import errors.

- [ ] **Step 3: Create the tools package + two tools, register it**
`src/mesa_mcp/datacite/tools/__init__.py` (copy the auto-import pattern from `src/mesa_mcp/irods/tools/__init__.py`):
```python
"""Auto-import every tool module so @register_tool runs on package import."""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

_PACKAGE_PATH = [str(Path(__file__).parent)]
for _module_info in pkgutil.iter_modules(_PACKAGE_PATH):
    importlib.import_module(f"{__name__}.{_module_info.name}")
del importlib, pkgutil, Path, _PACKAGE_PATH
```
`src/mesa_mcp/datacite/tools/template.py`:
```python
"""``mesa_datacite_template`` — return the DataCite field scaffold for form-driven entry."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mesa_mcp.datacite.schema import (
    ContributorType, DataCiteMetadata, DescriptionType, RelationType, ResourceTypeGeneral,
)
from mesa_mcp.server import register_tool


class TemplateInput(BaseModel):
    pass


_MANDATORY = {"identifier", "title", "creator", "publisher", "publicationYear", "resourceTypeGeneral"}
_REPEATABLE = {"title", "creator", "contributor", "subject", "date", "relatedIdentifier",
               "description", "rights", "geoLocation", "format", "size"}
_VOCAB = {
    "resourceTypeGeneral": [e.value for e in ResourceTypeGeneral],
    "contributorType": [e.value for e in ContributorType],
    "descriptionType": [e.value for e in DescriptionType],
    "relationType": [e.value for e in RelationType],
}


@register_tool(
    "mesa_datacite_template",
    "Return the DataCite 4.x field scaffold (field, required?, repeatable?, controlled "
    "vocabulary, canonical AVU key) to drive a complete, valid record.",
    input_model=TemplateInput,
)
async def handle_datacite_template(args: TemplateInput) -> dict[str, Any]:
    fields = []
    for name, info in DataCiteMetadata.model_fields.items():
        base = name[:-1] if name.endswith("s") and name not in ("publicationYear",) else name
        key = base.replace("List", "").rstrip("s") if base.endswith("List") else base
        fields.append({
            "field": _FIELD_ALIASES.get(name, name.rstrip("s") if name in
                     ("titles", "creators", "subjects", "contributors", "dates",
                      "relatedIdentifiers", "descriptions", "formats", "sizes") else name),
            "required": _FIELD_ALIASES.get(name, name) in _MANDATORY or name in
                        ("identifier", "publisher", "publicationYear", "resourceTypeGeneral"),
            "repeatable": (_FIELD_ALIASES.get(name, name) in _REPEATABLE),
            "vocabulary": _VOCAB.get(_FIELD_ALIASES.get(name, name)),
        })
    return {"schema": "DataCite-4.x", "fields": fields}


_FIELD_ALIASES = {
    "titles": "title", "creators": "creator", "subjects": "subject",
    "contributors": "contributor", "dates": "date",
    "relatedIdentifiers": "relatedIdentifier", "descriptions": "description",
    "rightsList": "rights", "geoLocations": "geoLocation",
    "formats": "format", "sizes": "size", "resourceTypeGeneral": "resourceTypeGeneral",
}
```
`src/mesa_mcp/datacite/tools/validate.py`:
```python
"""``mesa_datacite_validate`` — is this path's DataCite AVU set complete & DOI-ready?"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from mesa_mcp.datacite.transform import avus_to_datacite
from mesa_mcp.server import register_tool


class AvuItem(BaseModel):
    attribute: str
    value: str
    unit: str = ""


class ValidateInput(BaseModel):
    avus: list[AvuItem] = Field(..., description="The candidate DataCite AVUs to validate.")


_MANDATORY = ["identifier", "titles", "creators", "publisher", "publicationYear", "resourceTypeGeneral"]
_REPORT_NAME = {"titles": "title", "creators": "creator"}


@register_tool(
    "mesa_datacite_validate",
    "Validate DataCite AVUs against the 4.x kernel: report missing mandatory fields, "
    "invalid controlled-vocabulary values, and whether the record is DOI-ready.",
    input_model=ValidateInput,
)
async def handle_datacite_validate(args: ValidateInput) -> dict[str, Any]:
    avus = [a.model_dump() for a in args.avus]
    missing: list[str] = []
    errors: list[str] = []
    try:
        avus_to_datacite(avus)
    except (KeyError, ValidationError, ValueError) as exc:
        # Identify which mandatory keys are absent for a precise report.
        present = {a["attribute"] for a in avus}
        checks = {
            "identifier": "datacite.identifier",
            "title": "datacite.title.1.value",
            "creator": "datacite.creator.1.name",
            "publisher": "datacite.publisher",
            "publicationYear": "datacite.publicationYear",
            "resourceTypeGeneral": "datacite.resourceTypeGeneral",
        }
        missing = [field for field, key in checks.items() if key not in present]
        if not missing:
            errors.append(str(exc))
    return {
        "doi_ready": not missing and not errors,
        "missing_mandatory": missing,
        "errors": errors,
    }
```
Register the package in `src/mesa_mcp/server.py` — find the block that imports the tool packages (it already
imports `mesa_mcp.ols`, `mesa_mcp.irods.tools`, `mesa_mcp.ducklake.tools`) and add, alongside them:
```python
    import mesa_mcp.datacite.tools  # noqa: F401  (auto-registers DataCite tools)
```

- [ ] **Step 4: Run to verify it passes**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_tools.py -q`
Expected: PASS (3 passed). If `_REGISTRY` is not importable from `mesa_mcp.server`, read `server.py` to find
the registry's exported name and adjust the test import accordingly.

- [ ] **Step 5: Commit**
```bash
git add src/mesa_mcp/datacite/tools src/mesa_mcp/server.py tests/test_datacite_tools.py
git commit -m "feat(datacite): template + validate tools (auto-registered)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `mesa_avu_apply_datacite` (validate → bulk write → DuckLake mirror)

**Files:**
- Create: `src/mesa_mcp/datacite/tools/apply.py`
- Modify: `tests/test_datacite_tools.py`

Pattern: mirror `src/mesa_mcp/irods/tools/add_avus.py` (path validation, `add_avu_to_irods`, batched
`record_avu_changes`) but build the AVUs from a validated `DataCiteMetadata`. Mock iRODS in tests exactly as
`tests/test_ds_add_avus.py` does (patch `assert_allowed`, `default_pool().get`, `resolve_path_target`,
`add_avu_to_irods`, and `record_avu_changes`).

- [ ] **Step 1: Append the failing test** (read `tests/test_ds_add_avus.py` first for the exact mock setup)
```python
def test_apply_datacite_validates_then_bulk_writes(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    import mesa_mcp.datacite.tools.apply as ap
    from mesa_mcp.datacite.tools.apply import handle_apply_datacite, ApplyDataCiteInput
    from mesa_mcp.auth.models import AuthValue

    monkeypatch.setattr(ap, "assert_allowed", lambda target, auth: target)
    sess = MagicMock()
    monkeypatch.setattr(ap, "default_pool", lambda: MagicMock(get=lambda a: sess))
    monkeypatch.setattr(ap, "resolve_path_target", lambda s, p: "collection")
    written = []
    monkeypatch.setattr(ap, "add_avu_to_irods",
                        lambda s, p, t, avu: (written.append(avu) or avu))
    mirror = AsyncMock()
    monkeypatch.setattr(ap, "record_avu_changes", mirror)

    record = {
        "identifier": "10.25739/xyz", "identifierType": "DOI", "titles": ["T"],
        "creators": [{"name": "Alcock, Thomas"}], "publisher": "CyVerse",
        "publicationYear": 2016, "resourceTypeGeneral": "Image",
    }
    auth = AuthValue(username="tswetnam", zone="iplant", password="x")
    res = asyncio.run(handle_apply_datacite(
        ApplyDataCiteInput(target="/iplant/home/tswetnam/proj", record=record, naming="both"),
        auth_value=auth))
    assert res["written"] >= 7
    assert mirror.await_count == 1          # one batched DuckLake snapshot
    assert any(a["attribute"] == "datacite.identifier" for a in written)


def test_apply_datacite_rejects_invalid(monkeypatch):
    import asyncio
    import mesa_mcp.datacite.tools.apply as ap
    from mesa_mcp.datacite.tools.apply import handle_apply_datacite, ApplyDataCiteInput
    from mesa_mcp.errors import ToolError
    from mesa_mcp.auth.models import AuthValue
    auth = AuthValue(username="tswetnam", zone="iplant", password="x")
    bad = {"identifier": "x", "titles": ["T"], "creators": [{"name": "A"}],
           "publisher": "p", "publicationYear": 2016, "resourceTypeGeneral": "NotAType"}
    import pytest
    with pytest.raises(ToolError):
        asyncio.run(handle_apply_datacite(
            ApplyDataCiteInput(target="/iplant/home/tswetnam/proj", record=bad),
            auth_value=auth))
```

- [ ] **Step 2: Run to verify it fails**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_tools.py -q`
Expected: FAIL — `ModuleNotFoundError: ...datacite.tools.apply`.

- [ ] **Step 3: Create `apply.py`**
```python
"""``mesa_avu_apply_datacite`` — validate a DataCite record and bulk-write it as AVUs.

Validates against the DataCite 4.x model, serializes via datacite_to_avus, writes
every AVU to the iRODS path, then mirrors them into DuckLake as ONE snapshot.
Mirrors irods/tools/add_avus.py + ols/tools/avu_apply_term.py.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.datacite.schema import DataCiteMetadata
from mesa_mcp.datacite.transform import datacite_to_avus
from mesa_mcp.ducklake.client import DuckLakeMirrorError, record_avu_changes
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._avu_helpers import add_avu_to_irods, resolve_path_target
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool

TOOL_NAME = "mesa_avu_apply_datacite"


class ApplyDataCiteInput(BaseModel):
    target: str = Field(..., description="iRODS path of the data-object or collection.")
    record: dict[str, Any] = Field(..., description="A DataCite 4.x record (validated).")
    naming: str = Field("both", description="canonical | cyverse_template | both")


@register_tool(
    TOOL_NAME,
    "Validate a DataCite 4.x record and write it to an iRODS path as AVUs (canonical "
    "and/or CyVerse-template naming), mirrored to DuckLake as one snapshot.",
    input_model=ApplyDataCiteInput,
)
async def handle_apply_datacite(
    args: ApplyDataCiteInput, *, auth_value: AuthValue | None = None,
) -> dict[str, Any]:
    if auth_value is None:
        raise ToolError(code="unauthenticated", message=f"{TOOL_NAME} requires authentication.")
    try:
        record = DataCiteMetadata.model_validate(args.record)
    except ValidationError as exc:
        raise ToolError(code="datacite_invalid", message="record failed DataCite validation",
                        details={"errors": exc.errors(include_url=False)}) from exc
    avus = datacite_to_avus(record, naming=args.naming)

    norm = assert_allowed(args.target, auth_value)
    session = default_pool().get(auth_value)
    path_target = resolve_path_target(session, norm)
    written: list[dict[str, str]] = []
    changes: list[tuple[str, str, str, str]] = []
    errors: list[dict[str, str]] = []
    for avu in avus:
        try:
            w = add_avu_to_irods(session, norm, path_target,
                                 {"attribute": avu["attribute"], "value": avu["value"], "unit": ""})
            written.append(w)
            changes.append((w["attribute"], w["value"], w["unit"], "add"))
        except ToolError as exc:
            errors.append({"attribute": avu["attribute"], "error": str(exc)})
    result: dict[str, Any] = {"target": norm, "path_target_type": path_target,
                              "written": len(written), "errors": errors}
    if changes:
        try:
            await record_avu_changes(auth_value=auth_value, irods_path=norm,
                                     target_type=path_target, changes=changes,
                                     tool_name=TOOL_NAME, session=session)
        except DuckLakeMirrorError as exc:
            result["partial_failure"] = {"code": "ducklake_mirror_failed", "message": str(exc)}
    return result
```

- [ ] **Step 4: Run to verify it passes**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_tools.py -q`
Expected: PASS. (If `AuthValue(...)` needs different constructor args, read `src/mesa_mcp/auth/models.py`
and adjust the test's `AuthValue(...)` call — it only needs `.username` and `.zone` here.)

- [ ] **Step 5: Commit**
```bash
git add src/mesa_mcp/datacite/tools/apply.py tests/test_datacite_tools.py
git commit -m "feat(datacite): mesa_avu_apply_datacite (validate -> bulk write -> mirror)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: `mesa_datacite_export` tool + docs + full suite/lint/types

**Files:**
- Create: `src/mesa_mcp/datacite/tools/export.py`
- Modify: `tests/test_datacite_tools.py`; `CLAUDE.md` (one paragraph)

- [ ] **Step 1: Append the failing test**
```python
def test_export_tool_emits_xml():
    import asyncio
    from mesa_mcp.datacite.tools.export import handle_datacite_export, ExportInput
    avus = [
        {"attribute": "datacite.identifier", "value": "10.25739/xyz"},
        {"attribute": "datacite.identifierType", "value": "DOI"},
        {"attribute": "datacite.title.1.value", "value": "T"},
        {"attribute": "datacite.creator.1.name", "value": "Alcock, Thomas"},
        {"attribute": "datacite.publisher", "value": "CyVerse"},
        {"attribute": "datacite.publicationYear", "value": "2016"},
        {"attribute": "datacite.resourceTypeGeneral", "value": "Image"},
    ]
    res = asyncio.run(handle_datacite_export(ExportInput(avus=avus, format="xml")))
    assert "http://datacite.org/schema/kernel-4" in res["document"]
    assert "10.25739/xyz" in res["document"]
```

- [ ] **Step 2: Run to verify it fails**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_tools.py::test_export_tool_emits_xml -q`
Expected: FAIL — `ModuleNotFoundError: ...datacite.tools.export`.

- [ ] **Step 3: Create `export.py` (the tool)**
```python
"""``mesa_datacite_export`` — turn a path's DataCite AVUs into kernel-4 XML or JSON."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mesa_mcp.datacite.export import datacite_to_json, datacite_to_xml
from mesa_mcp.datacite.transform import avus_to_datacite
from mesa_mcp.errors import ToolError
from mesa_mcp.server import register_tool


class AvuItem(BaseModel):
    attribute: str
    value: str
    unit: str = ""


class ExportInput(BaseModel):
    avus: list[AvuItem] = Field(..., description="Canonical-naming DataCite AVUs from a path.")
    format: Literal["xml", "json"] = "xml"


@register_tool(
    "mesa_datacite_export",
    "Export DataCite AVUs as a DataCite 4.x XML (for DOI registration) or REST JSON document.",
    input_model=ExportInput,
)
async def handle_datacite_export(args: ExportInput) -> dict[str, Any]:
    try:
        record = avus_to_datacite([a.model_dump() for a in args.avus])
    except (KeyError, ValueError) as exc:
        raise ToolError(code="datacite_incomplete",
                        message=f"cannot build a DataCite record from these AVUs: {exc}") from exc
    doc = datacite_to_xml(record) if args.format == "xml" else datacite_to_json(record)
    return {"format": args.format, "document": doc}
```

- [ ] **Step 4: Run + full suite + lint + types**
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests/test_datacite_tools.py -q` → PASS.
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest tests -k datacite -q` → all datacite tests PASS.
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/python -m pytest -q` → no NEW failures (pre-existing `test_ols_client.py` mocker errors excepted).
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/ruff check src/mesa_mcp/datacite tests/test_datacite_*.py` → fix until "All checks passed!".
Run: `/Users/tswetnam/Desktop/mesa-ai-test/.venv/bin/mypy src/mesa_mcp/datacite` → resolve issues these files introduce.

- [ ] **Step 5: Docs + commit**
Add one paragraph to `CLAUDE.md` under the tool surface: a new **Group 2b — DataCite descriptive metadata**
listing `mesa_datacite_template`, `mesa_avu_apply_datacite`, `mesa_datacite_validate`, `mesa_datacite_export`,
the canonical `datacite.<field>[.<i>.<subfield>]` naming, and the `LEGACY_CROSSWALK` to CyVerse template names.
```bash
git add src/mesa_mcp/datacite/tools/export.py tests/test_datacite_tools.py CLAUDE.md
git commit -m "feat(datacite): export tool + docs; full suite/lint/types green

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (author check)

- **Spec coverage:** schema+enums+crosswalk (Tasks 1–2), transform canonical/template/both + round-trip
  (Tasks 3–5), export XML/JSON (Task 6), the four tools — template/validate/apply/export (Tasks 7–9),
  validation via Pydantic+enums (Tasks 1, 8), DuckLake mirror reuse (Task 8), docs (Task 9). The optional
  `MetadataStandard` generalization is intentionally deferred (YAGNI; noted in spec as future).
- **Naming consistency:** `DataCiteMetadata`, `datacite_to_avus(record, naming)`, `avus_to_datacite(avus)`,
  `datacite_to_xml`/`datacite_to_json`, tool handlers `handle_datacite_template`/`handle_datacite_validate`/
  `handle_apply_datacite`/`handle_datacite_export` — used identically across tasks.
- **Real iRODS unavailable in tests:** Task 8 mocks the iRODS + mirror seams exactly like
  `tests/test_ds_add_avus.py`; all other tests are pure (no network).
- **Adapt-on-contact notes:** Tasks 7–8 flag the two things to confirm against the live code — the registry
  symbol exported by `server.py`, and the `AuthValue` constructor — with instructions to read the source and
  adjust if they differ.
