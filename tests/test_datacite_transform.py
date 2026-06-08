# tests/test_datacite_transform.py
from mesa_mcp.datacite.schema import (
    Creator,
    DataCiteMetadata,
    ResourceTypeGeneral,
    Subject,
)
from mesa_mcp.datacite.transform import datacite_to_avus


def _rec():
    return DataCiteMetadata(
        identifier="10.25739/xyz",
        identifierType="DOI",
        titles=["U.Nottm_2016_RIPRleaf_images"],
        creators=[
            Creator(
                name="Alcock, Thomas",
                affiliation="University of Nottingham",
                nameIdentifier="0000-0001-2345-6789",
            )
        ],
        publisher="CyVerse Data Commons",
        publicationYear=2016,
        resourceTypeGeneral=ResourceTypeGeneral.Image,
        resourceType="leaf phenotyping",
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


def test_cyverse_template_naming_joins_repeatables():
    avus = datacite_to_avus(_rec(), naming="cyverse_template")
    pairs = {(a["attribute"], a["value"]) for a in avus}
    assert ("datacite.title", "U.Nottm_2016_RIPRleaf_images") in pairs
    assert ("datacite.creator", "Alcock, Thomas") in pairs
    assert ("creatorAffiliation", "University of Nottingham") in pairs
    assert ("datacite.resourcetype", "Image") in pairs  # general -> legacy resourcetype
    assert ("ResourceType", "leaf phenotyping") in pairs
    assert ("Subject", "Brassica, Phenotyping") in pairs  # repeatables joined
    assert ("identifierType", "DOI") in pairs


def test_both_is_superset():
    a = {(x["attribute"], x["value"]) for x in datacite_to_avus(_rec(), naming="canonical")}
    b = {(x["attribute"], x["value"]) for x in datacite_to_avus(_rec(), naming="cyverse_template")}
    both = {(x["attribute"], x["value"]) for x in datacite_to_avus(_rec(), naming="both")}
    assert a <= both and b <= both


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
