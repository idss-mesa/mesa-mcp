"""``ds_list_policies`` — list registered Policy Composition Framework policies.

This is a best-effort tool: iRODS does not expose its PCF state through
PRC, so the tool returns a documented stub envelope. See
:mod:`mesa_mcp.irods.policies` for details.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import require_current_auth_value
from mesa_mcp.errors import ToolError
from mesa_mcp.irods import policies as policy_helpers
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class ListPoliciesInput(BaseModel):
    """Input schema for ``ds_list_policies`` (no arguments)."""


@register_tool(
    "ds_list_policies",
    (
        "List active policies in the iRODS Policy Composition Framework. "
        "iRODS does not expose PCF state through PRC; this tool returns "
        "a documented stub envelope with a ``note`` describing the "
        "limitation."
    ),
    input_model=ListPoliciesInput,
)
async def handle_list_policies(
    _args: ListPoliciesInput,
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
    return policy_helpers.list_pcf_policies(sess)
