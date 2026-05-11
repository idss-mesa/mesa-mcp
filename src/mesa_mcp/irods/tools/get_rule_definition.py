"""``ds_get_rule_definition`` — best-effort source for a named rule.

iRODS keeps its rule base on the server's filesystem, not the catalog,
so PRC has no way to fetch a rule's source. This tool returns the
known-empty result plus a ``note`` so an MCP client can detect the
limitation. Admins who want this surface should install an
introspection rule on the server and invoke it via ``ds_execute_rule``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import require_current_auth_value
from mesa_mcp.errors import ToolError
from mesa_mcp.irods import rules as rule_helpers
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class GetRuleDefinitionInput(BaseModel):
    """Input schema for ``ds_get_rule_definition``."""

    name: str = Field(
        ...,
        min_length=1,
        description="Name of the rule to introspect.",
    )


@register_tool(
    "ds_get_rule_definition",
    (
        "Return the source of a named iRODS rule. iRODS does not expose "
        "rule sources through PRC; this is a best-effort tool whose "
        "``definition`` field is None on most servers."
    ),
    input_model=GetRuleDefinitionInput,
)
async def handle_get_rule_definition(
    args: GetRuleDefinitionInput,
    *,
    auth_value: AuthValue | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    auth = auth_value or require_current_auth_value()
    if auth.is_anonymous():
        raise ToolError(
            code="forbidden",
            message="anonymous user is not allowed to introspect rules",
            details={"tool": "ds_get_rule_definition"},
        )
    sess = session or default_pool().get(auth)
    return rule_helpers.get_rule_definition(sess, args.name)
