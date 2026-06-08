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


# Mapping from human-readable mandatory field name to the canonical AVU key
# that must be present for the record to be valid.
_MANDATORY_CHECKS: dict[str, str] = {
    "identifier": "datacite.identifier",
    "title": "datacite.title.1.value",
    "creator": "datacite.creator.1.name",
    "publisher": "datacite.publisher",
    "publicationYear": "datacite.publicationYear",
    "resourceTypeGeneral": "datacite.resourceTypeGeneral",
}


@register_tool(
    "mesa_datacite_validate",
    "Validate DataCite AVUs against the 4.x kernel: report missing mandatory fields, "
    "invalid controlled-vocabulary values, and whether the record is DOI-ready.",
    input_model=ValidateInput,
)
async def handle_datacite_validate(args: ValidateInput) -> dict[str, Any]:
    """Validate a set of DataCite AVUs and report readiness."""
    avus = [a.model_dump() for a in args.avus]
    missing: list[str] = []
    errors: list[str] = []

    # First, check which mandatory canonical keys are simply absent.
    present = {a["attribute"] for a in avus}
    missing = [field for field, key in _MANDATORY_CHECKS.items() if key not in present]

    if not missing:
        # All mandatory keys present — try to fully parse the record to catch
        # validation errors (bad enum values, year out of range, etc.).
        try:
            avus_to_datacite(avus)
        except (KeyError, ValidationError, ValueError) as exc:
            errors.append(str(exc))

    return {
        "doi_ready": not missing and not errors,
        "missing_mandatory": missing,
        "errors": errors,
    }
