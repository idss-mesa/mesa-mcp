# tests/test_datacite_export.py
import xml.etree.ElementTree as ET

from mesa_mcp.datacite.export import datacite_to_json, datacite_to_xml
from mesa_mcp.datacite.schema import Creator, DataCiteMetadata, ResourceTypeGeneral


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
