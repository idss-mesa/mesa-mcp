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


def test_apply_datacite_validates_then_bulk_writes(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    import mesa_mcp.datacite.tools.apply as ap
    from mesa_mcp.auth.models import AuthValue
    from mesa_mcp.datacite.tools.apply import ApplyDataCiteInput, handle_apply_datacite

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
    import pytest

    from mesa_mcp.auth.models import AuthValue
    from mesa_mcp.datacite.tools.apply import ApplyDataCiteInput, handle_apply_datacite
    from mesa_mcp.errors import ToolError

    auth = AuthValue(username="tswetnam", zone="iplant", password="x")
    bad = {"identifier": "x", "titles": ["T"], "creators": [{"name": "A"}],
           "publisher": "p", "publicationYear": 2016, "resourceTypeGeneral": "NotAType"}
    with pytest.raises(ToolError):
        asyncio.run(handle_apply_datacite(
            ApplyDataCiteInput(target="/iplant/home/tswetnam/proj", record=bad),
            auth_value=auth))
