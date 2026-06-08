import pytest
from pydantic import ValidationError

from mesa_mcp.datacite.schema import (
    Creator,
    DataCiteMetadata,
    ResourceTypeGeneral,
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


def test_legacy_crosswalk_covers_template_fields():
    from mesa_mcp.datacite.schema import LEGACY_CROSSWALK
    # Every CyVerse DOI-request CSV column maps to a kernel field.
    for col in ["datacite.title", "creatorAffiliation", "datacite.resourcetype",
                "ResourceType", "Subject", "contributorName", "identifierType",
                "Rights", "Description", "descriptionType", "compressed_data"]:
        assert col in LEGACY_CROSSWALK, f"missing crosswalk for {col}"
    assert LEGACY_CROSSWALK["datacite.resourcetype"] == "resourceTypeGeneral"
    assert LEGACY_CROSSWALK["ResourceType"] == "resourceType"
