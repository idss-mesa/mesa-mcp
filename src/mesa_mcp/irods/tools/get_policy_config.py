"""``ds_get_policy_config`` — fetch a single PCF policy's configuration.

Like :mod:`mesa_mcp.irods.tools.list_policies`, this is a best-effort
tool — iRODS does not expose PCF config through PRC. The return shape
is ``{"name": ..., "config": None, "note": ...}``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import require_current_auth_value
from mesa_mcp.errors import ToolError
from mesa_mcp.irods import policies as policy_helpers
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class GetPolicyConfigInput(BaseModel):
    """Input schema for ``ds_get_policy_config``."""

    name: str = Field(
        ...,
        min_length=1,
        description="Name of the PCF policy to introspect.",
    )


@register_tool(
    "ds_get_policy_config",
    (
        "Return the configuration of a named Policy Composition Framework "
        "policy. iRODS does not expose PCF config through PRC; this is a "
        "stub that returns ``config=None`` and a ``note`` documenting the "
        "limitation."
    ),
    input_model=GetPolicyConfigInput,
)
async def handle_get_policy_config(
    args: GetPolicyConfigInput,
    *,
    auth_value: AuthValue | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    auth = auth_value or require_current_auth_value()
    if auth.is_anonymous():
        raise ToolError(
            code="forbidden",
            message="anonymous user is not allowed to read policy config",
            details={"tool": "ds_get_policy_config"},
        )
    sess = session or default_pool().get(auth)
    return policy_helpers.get_pcf_policy_config(sess, args.name)
