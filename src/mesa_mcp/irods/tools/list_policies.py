"""``ds_list_policies`` — list registered Policy Composition Framework policies.

This is a best-effort tool: iRODS does not expose its PCF state through
PRC, so the tool returns a documented stub envelope. See
:mod:`mesa_mcp.irods.policies` for details.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import require_current_auth_value
from mesa_mcp.errors import ToolError
from mesa_mcp.irods import policies as policy_helpers
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class ListPoliciesInput(BaseModel):
    """Input schema for ``ds_list_policies``."""

    project_path: str | None = Field(
        default=None,
        description=(
            "Project root collection whose MESA policy AVUs "
            "(``mesa.policy.*``) should be listed. Omit to return only the "
            "server-side Policy Composition Framework envelope."
        ),
    )


@register_tool(
    "ds_list_policies",
    (
        "List policies in effect for the Data Store. With ``project_path``, "
        "returns the MESA policy AVUs (``mesa.policy.*``) set on that "
        "project root — the policies mesa-mcp itself honours. Always "
        "includes the server-side Policy Composition Framework envelope; "
        "iRODS does not expose PCF state through PRC, so that part is a "
        "documented stub."
    ),
    input_model=ListPoliciesInput,
)
async def handle_list_policies(
    args: ListPoliciesInput,
    *,
    auth_value: AuthValue | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    auth = auth_value or require_current_auth_value()
    if auth.is_anonymous():
        raise ToolError(
            code="forbidden",
            message="anonymous user is not allowed to list policies",
            details={"tool": "ds_list_policies"},
        )
    sess = session or default_pool().get(auth)

    # The PCF envelope is always present so the response shape does not
    # change depending on whether a path was supplied.
    result: dict[str, Any] = dict(policy_helpers.list_pcf_policies(sess))

    if args.project_path is None:
        result["mesa_policies"] = None
        result["mesa_policies_note"] = (
            "Pass project_path to list the mesa.policy.* AVUs that mesa-mcp "
            "enforces on a project root."
        )
        return result

    # Access-check before reading AVUs: a policy listing reveals how a
    # collection is governed, so it is subject to the same path allowlist
    # as any other read.
    norm = assert_allowed(args.project_path, auth)
    result["project_path"] = norm
    result["mesa_policies"] = policy_helpers.list_mesa_policies(sess, norm)
    return result
