"""``mesa_datacite_template`` — return the DataCite field scaffold for form-driven entry."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mesa_mcp.datacite.schema import (
    ContributorType,
    DescriptionType,
    RelationType,
    ResourceTypeGeneral,
)
from mesa_mcp.server import register_tool

# Canonical field name -> singular display name used in the scaffold output.
# Plural model field names are de-pluralised here so the test can check for
# "title", "creator", etc. (not "titles", "creators").
_FIELD_ALIASES: dict[str, str] = {
    "titles": "title",
    "creators": "creator",
    "subjects": "subject",
    "contributors": "contributor",
    "dates": "date",
    "relatedIdentifiers": "relatedIdentifier",
    "descriptions": "description",
    "rightsList": "rights",
    "geoLocations": "geoLocation",
    "formats": "format",
    "sizes": "size",
}

# Fields that are mandatory per the DataCite 4.x kernel spec.
_MANDATORY_FIELDS: frozenset[str] = frozenset(
    {"identifier", "title", "creator", "publisher", "publicationYear", "resourceTypeGeneral"}
)

# Fields that accept multiple values (repeatable).
_REPEATABLE_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "creator",
        "contributor",
        "subject",
        "date",
        "relatedIdentifier",
        "description",
        "rights",
        "geoLocation",
        "format",
        "size",
    }
)

# Controlled-vocabulary lists for fields that have one.
_VOCAB: dict[str, list[str]] = {
    "resourceTypeGeneral": [e.value for e in ResourceTypeGeneral],
    "contributorType": [e.value for e in ContributorType],
    "descriptionType": [e.value for e in DescriptionType],
    "relationType": [e.value for e in RelationType],
}


class TemplateInput(BaseModel):
    """No input required — returns the static DataCite field scaffold."""


@register_tool(
    "mesa_datacite_template",
    "Return the DataCite 4.x field scaffold (field, required?, repeatable?, controlled "
    "vocabulary, canonical AVU key) to drive a complete, valid record.",
    input_model=TemplateInput,
)
async def handle_datacite_template(args: TemplateInput) -> dict[str, Any]:
    """Return the DataCite 4.x field scaffold."""
    # Explicit ordered field list mirrors the DataCiteMetadata model order.
    model_fields = [
        "identifier",
        "identifierType",
        "titles",
        "creators",
        "publisher",
        "publicationYear",
        "resourceTypeGeneral",
        "resourceType",
        "subjects",
        "contributors",
        "dates",
        "relatedIdentifiers",
        "descriptions",
        "rightsList",
        "geoLocations",
        "language",
        "formats",
        "sizes",
        "version",
    ]

    fields: list[dict[str, Any]] = []
    for model_name in model_fields:
        display_name = _FIELD_ALIASES.get(model_name, model_name)
        fields.append(
            {
                "field": display_name,
                "required": display_name in _MANDATORY_FIELDS,
                "repeatable": display_name in _REPEATABLE_FIELDS,
                "vocabulary": _VOCAB.get(display_name),
            }
        )

    return {"schema": "DataCite-4.x", "fields": fields}
