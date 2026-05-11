"""``ds_list_rules`` — best-effort enumeration of iRODS rules.

iRODS does not expose its rule base over PRC; see the helper module
:mod:`mesa_mcp.irods.rules` for the rationale. This tool returns a
``{"rules": [...], "note": ...}`` envelope where the list may be empty
and the ``note`` documents the limitation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import require_current_auth_value
from mesa_mcp.errors import ToolError
from mesa_mcp.irods import rules as rule_helpers
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class ListRulesInput(BaseModel):
    """Input schema for ``ds_list_rules`` (no arguments)."""


@register_tool(
    "ds_list_rules",
    (
        "List iRODS rules visible to the caller. Returns a best-effort list "
        "of delayed rules; the static rule base is not exposed by PRC and "
        "the ``note`` field documents that limitation."
    ),
    input_model=ListRulesInput,
)
async def handle_list_rules(
    _args: ListRulesInput,
    *,
    auth_value: AuthValue | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    auth = auth_value or require_current_auth_value()
    if auth.is_anonymous():
        raise ToolError(
            code="forbidden",
            message="anonymous user is not allowed to list rules",
            details={"tool": "ds_list_rules"},
        )
    sess = session or default_pool().get(auth)
    return rule_helpers.list_rules(sess)
