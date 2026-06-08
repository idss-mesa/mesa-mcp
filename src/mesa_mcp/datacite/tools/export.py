"""``mesa_datacite_export`` — turn a path's DataCite AVUs into kernel-4 XML or JSON."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mesa_mcp.datacite.export import datacite_to_json, datacite_to_xml
from mesa_mcp.datacite.transform import avus_to_datacite
from mesa_mcp.errors import ToolError
from mesa_mcp.server import register_tool


class AvuItem(BaseModel):
    attribute: str
    value: str
    unit: str = ""


class ExportInput(BaseModel):
    avus: list[AvuItem] = Field(..., description="Canonical-naming DataCite AVUs from a path.")
    format: Literal["xml", "json"] = "xml"


@register_tool(
    "mesa_datacite_export",
    "Export DataCite AVUs as a DataCite 4.x XML (for DOI registration) or REST JSON document.",
    input_model=ExportInput,
)
async def handle_datacite_export(args: ExportInput) -> dict[str, Any]:
    try:
        record = avus_to_datacite([a.model_dump() for a in args.avus])
    except (KeyError, ValueError) as exc:
        raise ToolError(
            code="datacite_incomplete",
            message=f"cannot build a DataCite record from these AVUs: {exc}",
        ) from exc
    doc = datacite_to_xml(record) if args.format == "xml" else datacite_to_json(record)
    return {"format": args.format, "document": doc}
