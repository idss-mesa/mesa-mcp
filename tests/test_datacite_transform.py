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
