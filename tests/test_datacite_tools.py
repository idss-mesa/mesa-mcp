# tests/test_datacite_tools.py
import asyncio

from mesa_mcp.server import _REGISTRY


def test_datacite_tools_registered():
    for name in ("mesa_datacite_template", "mesa_datacite_validate"):
        assert name in _REGISTRY


def test_template_lists_mandatory_fields():
    from mesa_mcp.datacite.tools.template import TemplateInput, handle_datacite_template
    res = asyncio.run(handle_datacite_template(TemplateInput()))
    mandatory = {f["field"] for f in res["fields"] if f["required"]}
    assert {"identifier", "title", "creator", "publisher",
            "publicationYear", "resourceTypeGeneral"} <= mandatory


def test_validate_flags_missing_doi():
    from mesa_mcp.datacite.tools.validate import ValidateInput, handle_datacite_validate
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
