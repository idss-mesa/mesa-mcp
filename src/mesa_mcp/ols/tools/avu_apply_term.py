"""``mesa_avu_apply_term`` — composite OLS-term → iRODS-AVU → DuckLake.

Combines three steps that are otherwise separate tools:

1. Validate the iRODS path against the caller's accessible paths.
2. Resolve an OLS term (by IRI or CURIE) to ``{label, curie, iri}`` via
   the OLS singleton (no network if both label and curie are passed in).
3. Build the canonical AVU triple via ``ontology_annotations_to_avus`` and
   write it through the same helper ``ds_add_avu`` uses. The same helper
   then runs the DuckLake mirror.

The whole point of this tool is "one call, full provenance" for an agent
tagging a file with an ontology term.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.ducklake.client import DuckLakeMirrorError, record_avu_change
from mesa_mcp.errors import InputRequired, ToolError
from mesa_mcp.irods._avu_helpers import add_avu_to_irods, resolve_path_target
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.ols import get_default_client
from mesa_mcp.ols.client import OLSAPIError, OLSClient, _label_to_snake
from mesa_mcp.ols.transform import ontology_annotations_to_avus
from mesa_mcp.server import register_tool

TOOL_NAME = "mesa_avu_apply_term"

#: How many OLS hits to offer when asking the user to disambiguate. Enough
#: to cover a near-miss, short enough to read in a picker.
MAX_TERM_CANDIDATES = 8


def _search_candidates(
    ontology_id: str,
    query: str,
    *,
    client: OLSClient | None = None,
) -> list[dict[str, str]]:
    """Look up candidate OLS terms to offer the user.

    Returns ``[]`` on any OLS failure: a disambiguation prompt is a
    convenience, so an OLS outage should surface as the ordinary
    "supply iri or curie" error rather than a confusing elicitation.
    """
    ols = client or get_default_client()
    try:
        hits = ols.search_terms(
            query=query, ontology_id=ontology_id, size=MAX_TERM_CANDIDATES
        )
    except OLSAPIError:
        return []
    candidates: list[dict[str, str]] = []
    for hit in hits[:MAX_TERM_CANDIDATES]:
        iri = hit.get("iri") or ""
        if not iri:
            continue
        candidates.append(
            {
                "iri": iri,
                "curie": hit.get("curie") or "",
                "label": hit.get("label") or "",
                "description": (hit.get("description") or "")[:200],
            }
        )
    return candidates


def _candidate_schema(candidates: list[dict[str, str]]) -> dict[str, Any]:
    """Build the JSON Schema 2020-12 form describing the choice."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "iri": {
                "type": "string",
                "title": "Ontology term",
                "description": "IRI of the term to apply.",
                "enum": [c["iri"] for c in candidates],
                "enumNames": [
                    f"{c['label']} ({c['curie']})" if c["curie"] else c["label"]
                    for c in candidates
                ],
            }
        },
        "required": ["iri"],
    }


def _resolve_elicited_choice(
    elicited: dict[str, Any] | None,
) -> tuple[str | None, str | None, str | None]:
    """Turn an MRTR follow-up into ``(iri, curie, label)``.

    The returned continuation is client-controlled, so the chosen IRI is
    only honoured when it is one this server actually offered. That check
    is what keeps a tampered ``requestState`` from steering the write to
    an arbitrary term; it costs nothing because the candidate list travels
    in the same blob.
    """
    if not elicited:
        return None, None, None

    response = (elicited.get("responses") or {}).get("term_choice")
    if response is None:
        return None, None, None

    # ElicitResult: honour an explicit decline/cancel.
    action = getattr(response, "action", None)
    if action is None and isinstance(response, dict):
        action = response.get("action")
    if action in ("decline", "cancel"):
        raise ToolError(
            code="invalid_argument",
            message="Term selection was cancelled; no AVU was written.",
            details={},
        )

    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content")
    if not isinstance(content, dict):
        return None, None, None

    chosen = content.get("iri")
    if not isinstance(chosen, str) or not chosen:
        return None, None, None

    offered = (elicited.get("state") or {}).get("candidates") or []
    for candidate in offered:
        if isinstance(candidate, dict) and candidate.get("iri") == chosen:
            return chosen, candidate.get("curie") or None, candidate.get("label") or None

    raise ToolError(
        code="invalid_argument",
        message="Selected term was not among the offered candidates.",
        details={},
    )


class ApplyTermInput(BaseModel):
    """Input schema for ``mesa_avu_apply_term``."""

    path: str = Field(
        ...,
        description="Absolute iRODS path of the data object or collection to tag.",
    )
    ontology_id: str = Field(
        ...,
        min_length=1,
        description="Ontology identifier (e.g. 'envo').",
    )
    value: str = Field(
        ...,
        min_length=1,
        description="User-supplied AVU value. Often the term label, but free-form.",
    )
    iri: str | None = Field(
        None,
        description="Full IRI of the OLS term. Either ``iri`` or ``curie`` is required.",
    )
    curie: str | None = Field(
        None,
        description="CURIE of the OLS term (e.g. 'ENVO:00000428').",
    )
    label: str | None = Field(
        None,
        description=(
            "Optional term label. When omitted, the label is looked up "
            "via OLS so the AVU attribute can be ``<ontology>.<snake_case_label>``."
        ),
    )


@register_tool(
    TOOL_NAME,
    "Resolve an OLS term, build the canonical AVU triple "
    "(<ontology>.<snake_label>, <value>, <CURIE>), write it to the iRODS "
    "path, and record the change in the project's DuckLake. Composite of "
    "mesa_avu_from_term + ds_add_avu, in one call.",
    input_model=ApplyTermInput,
)
async def handle_mesa_avu_apply_term(
    args: ApplyTermInput,
    *,
    auth_value: AuthValue | None = None,
    client: OLSClient | None = None,
    elicited: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the composite pipeline. Returns the AVU written + DuckLake info."""
    if auth_value is None:
        raise ToolError(
            code="unauthenticated",
            message=f"{TOOL_NAME} requires an authenticated caller.",
        )

    # 1. Path safety.
    #
    # Deliberately ahead of the MRTR branch below, and re-run on resume:
    # access is always decided from the caller's live credentials, never
    # from anything that round-tripped through the client.
    norm = assert_allowed(args.path, auth_value)

    # 1a. Resolve an MRTR follow-up, if this is one.
    chosen_iri, chosen_curie, chosen_label = _resolve_elicited_choice(elicited)

    iri_in = args.iri or chosen_iri
    curie_in = args.curie or chosen_curie

    if not iri_in and not curie_in:
        # No term identified. Rather than failing, search OLS and ask the
        # user to pick (Multi Round-Trip Requests, MCP 2026-07-28).
        candidates = _search_candidates(
            args.ontology_id, args.value, client=client
        )
        if not candidates:
            raise ToolError(
                code="invalid_argument",
                message=(
                    "Either 'iri' or 'curie' must be supplied, and no OLS term "
                    f"in {args.ontology_id!r} matched {args.value!r} to offer "
                    "as a choice."
                ),
                details={"ontology_id": args.ontology_id, "value": args.value},
            )
        raise InputRequired(
            message=(
                f"Which {args.ontology_id.upper()} term describes "
                f"{args.value!r}?"
            ),
            schema=_candidate_schema(candidates),
            # Only the question travels — no path, no identity, nothing
            # that would grant anything if the client edited it.
            state={
                "tool": TOOL_NAME,
                "ontology_id": args.ontology_id,
                "candidates": candidates,
            },
            key="term_choice",
        )

    # 2. Resolve the term.
    label = args.label or chosen_label
    curie = curie_in or ""
    iri = iri_in or ""

    if label is None and iri_in:
        ols = client or get_default_client()
        try:
            term = ols.get_term(args.ontology_id, iri_in)
        except OLSAPIError as exc:
            raise ToolError(
                code="upstream_error",
                message=str(exc),
                details={"status_code": exc.status_code},
            ) from exc
        if term is None:
            raise ToolError(
                code="not_found",
                message=f"Term {iri_in!r} not found in ontology {args.ontology_id!r}.",
                details={"ontology_id": args.ontology_id, "iri": iri_in},
            )
        label = term.get("label", "")
        curie = curie or term.get("curie", "")
        iri = iri or term.get("iri", "")

    if not label:
        raise ToolError(
            code="invalid_argument",
            message=(
                "Could not determine a term label. Supply 'label' explicitly or "
                "'iri' so the OLS lookup can resolve one."
            ),
            details={},
        )

    snake_key = _label_to_snake(label)
    if not snake_key:
        raise ToolError(
            code="invalid_argument",
            message=f"Label {label!r} could not be converted to a snake_case key.",
            details={"label": label},
        )

    # 3. Build the AVU via the same transform the portal uses.
    avus = ontology_annotations_to_avus(
        args.ontology_id,
        [{"key": snake_key, "value": args.value, "curie": curie}],
    )
    if not avus:
        raise ToolError(
            code="invalid_argument",
            message="Could not build an AVU from the supplied term + value.",
            details={"ontology_id": args.ontology_id, "value": args.value},
        )
    avu = avus[0]

    # 4. Write through the shared helper (same code path as ds_add_avu).
    session = default_pool().get(auth_value)
    path_target = resolve_path_target(session, norm)
    written = add_avu_to_irods(session, norm, path_target, avu)

    # 5. Mirror to DuckLake.
    result: dict[str, Any] = {
        "path": norm,
        "target_type": path_target,
        "avu": written,
        "term": {
            "ontologyId": args.ontology_id.lower(),
            "label": label,
            "curie": curie,
            "iri": iri,
        },
    }
    try:
        await record_avu_change(
            auth_value=auth_value,
            irods_path=norm,
            target_type=path_target,
            attribute=written["attribute"],
            value=written["value"],
            unit=written["unit"],
            op="add",
            tool_name=TOOL_NAME,
            session=session,
        )
    except DuckLakeMirrorError as exc:
        result["partial_failure"] = {
            "code": "ducklake_mirror_failed",
            "message": str(exc),
            "project_id": str(exc.project_id) if exc.project_id else None,
        }
    return result
