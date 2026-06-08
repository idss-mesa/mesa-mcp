"""DataCite record <-> iRODS AVU triples.

Canonical naming: scalars -> ``datacite.<field>``; repeatable/structured entities
-> indexed with sub-fields (``datacite.creator.1.name`` ...). This preserves the
grouping that flat AVUs lose, so a record can round-trip to/from AVUs and to XML.
"""

from __future__ import annotations

import re as _re
from typing import Any

from mesa_mcp.datacite.schema import (
    Contributor,
    Creator,
    DataCiteMetadata,
    DateInfo,
    Description,
    GeoLocation,
    RelatedIdentifier,
    ResourceTypeGeneral,
    Rights,
    Subject,
)

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
    out += _entity_avus(
        "datacite.creator",
        rec.creators,
        ["name", "nameType", "affiliation", "nameIdentifier", "nameIdentifierScheme"],
    )
    out += _entity_avus(
        "datacite.contributor",
        rec.contributors,
        ["name", "contributorType", "affiliation"],
    )
    out += _entity_avus("datacite.subject", rec.subjects, ["value", "subjectScheme"])
    out += _entity_avus("datacite.date", rec.dates, ["date", "dateType"])
    out += _entity_avus(
        "datacite.relatedIdentifier",
        rec.relatedIdentifiers,
        ["value", "relatedIdentifierType", "relationType"],
    )
    out += _entity_avus(
        "datacite.description", rec.descriptions, ["value", "descriptionType"]
    )
    out += _entity_avus("datacite.rights", rec.rightsList, ["value", "rightsURI"])
    out += _entity_avus(
        "datacite.geoLocation", rec.geoLocations, ["place", "point", "box"]
    )
    for i, fmt in enumerate(rec.formats, start=1):
        out.append(_avu(f"datacite.format.{i}", fmt))
    for i, sz in enumerate(rec.sizes, start=1):
        out.append(_avu(f"datacite.size.{i}", sz))
    return out


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


def datacite_to_avus(record: DataCiteMetadata, naming: str = "canonical") -> list[_Avu]:
    """Serialize a DataCite record to AVU triples.

    ``naming`` in {``canonical``, ``cyverse_template``, ``both``}.
    """
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


_INDEXED = _re.compile(r"^datacite\.(\w+)\.(\d+)\.(\w+)$")

_ENTITY_MODELS: dict[str, type] = {
    "creator": Creator,
    "contributor": Contributor,
    "subject": Subject,
    "date": DateInfo,
    "relatedIdentifier": RelatedIdentifier,
    "description": Description,
    "rights": Rights,
    "geoLocation": GeoLocation,
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
            scalars[attr[len("datacite.") :]] = val

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
        resourceTypeGeneral=ResourceTypeGeneral(scalars["resourceTypeGeneral"]),
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
