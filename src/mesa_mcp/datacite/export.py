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
            ni = ET.SubElement(
                ce,
                f"{{{_NS}}}nameIdentifier",
                nameIdentifierScheme=c.nameIdentifierScheme or "ORCID",
            )
            ni.text = c.nameIdentifier
    titles = ET.SubElement(root, f"{{{_NS}}}titles")
    for t in rec.titles:
        ET.SubElement(titles, f"{{{_NS}}}title").text = t
    ET.SubElement(root, f"{{{_NS}}}publisher").text = rec.publisher
    ET.SubElement(root, f"{{{_NS}}}publicationYear").text = str(rec.publicationYear)
    rt = ET.SubElement(
        root,
        f"{{{_NS}}}resourceType",
        resourceTypeGeneral=rec.resourceTypeGeneral.value,
    )
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
        for ct in rec.contributors:
            ce = ET.SubElement(
                cons,
                f"{{{_NS}}}contributor",
                contributorType=ct.contributorType.value,
            )
            ET.SubElement(ce, f"{{{_NS}}}contributorName").text = ct.name
    if rec.descriptions:
        des = ET.SubElement(root, f"{{{_NS}}}descriptions")
        for d in rec.descriptions:
            ET.SubElement(
                des,
                f"{{{_NS}}}description",
                descriptionType=d.descriptionType.value,
            ).text = d.value
    if rec.rightsList:
        rl = ET.SubElement(root, f"{{{_NS}}}rightsList")
        for r in rec.rightsList:
            el = ET.SubElement(rl, f"{{{_NS}}}rights")
            if r.rightsURI:
                el.set("rightsURI", r.rightsURI)
            el.text = r.value
    return ET.tostring(root, encoding="unicode")


def datacite_to_json(rec: DataCiteMetadata) -> str:
    attrs: dict[str, object] = {
        "doi": rec.identifier,
        "titles": [{"title": t} for t in rec.titles],
        "creators": [
            {
                "name": c.name,
                **({"affiliation": [c.affiliation]} if c.affiliation else {}),
                **(
                    {
                        "nameIdentifiers": [
                            {
                                "nameIdentifier": c.nameIdentifier,
                                "nameIdentifierScheme": c.nameIdentifierScheme or "ORCID",
                            }
                        ]
                    }
                    if c.nameIdentifier
                    else {}
                ),
            }
            for c in rec.creators
        ],
        "publisher": rec.publisher,
        "publicationYear": rec.publicationYear,
        "types": {
            "resourceTypeGeneral": rec.resourceTypeGeneral.value,
            **({"resourceType": rec.resourceType} if rec.resourceType else {}),
        },
        "subjects": [{"subject": s.value} for s in rec.subjects],
        "descriptions": [
            {"description": d.value, "descriptionType": d.descriptionType.value}
            for d in rec.descriptions
        ],
    }
    return json.dumps({"data": {"type": "dois", "attributes": attrs}}, indent=2)
