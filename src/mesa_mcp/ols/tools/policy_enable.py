"""``mesa_policy_enable`` and ``mesa_policy_disable`` — toggle MESA project policies.

MESA policies are recorded as AVUs on the project root collection
with the attribute pattern ``mesa.policy.<name>=true``. These tools:

1. Validate the path exists and is a collection (policies don't make
   sense on individual data objects).
2. Write (or remove) the AVU through ``python-irodsclient``.
3. Record the change into the project's DuckLake so the policy toggle
   appears in the audit trail.

Both tools live under :mod:`mesa_mcp.ols.tools` to match the existing
mesa-specific tool location pattern (the ``mesa_*`` prefix in the tool
registry — the directory name is incidental).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import require_current_auth_value
from mesa_mcp.ducklake.client import DuckLakeMirrorError, record_avu_change
from mesa_mcp.errors import ToolError
from mesa_mcp.irods import policies as policy_helpers
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class PolicyToggleInput(BaseModel):
    """Input schema for ``mesa_policy_enable``/``mesa_policy_disable``."""

    project_path: str = Field(
        ...,
        min_length=1,
        description="iRODS path of the project root collection.",
    )
    policy_name: str = Field(
        ...,
        min_length=1,
        description=(
            "Short policy identifier (becomes the suffix of the "
            "``mesa.policy.<name>`` AVU)."
        ),
    )


def _assert_collection(session: Any, path: str) -> None:
    """Validate that ``path`` is a collection.

    Policy AVUs are bound to project roots; writing them onto a data
    object would silently no-op our discovery code that walks
    ``mesa.policy.*`` AVUs on collections.
    """
    try:
        session.collections.get(path)
    except Exception as exc:  # noqa: BLE001 - PRC raises a variety of types
        raise ToolError(
            code="invalid_argument",
            message=(
                f"Project path {path!r} is not a collection (policies "
                f"apply only to collections)."
            ),
            details={"path": path, "cause": str(exc)},
        ) from exc


async def _record_into_ducklake(
    *,
    project_path: str,
    policy_name: str,
    enabled: bool,
    auth: AuthValue,
    session: Any,
    tool_name: str,
) -> None:
    """Append the policy toggle as an AVU change to the project's DuckLake.

    Delegates to :func:`mesa_mcp.ducklake.client.record_avu_change`, which
    is the canonical mirror entry point: it walks the path's parents
    looking for a MESA-enabled root, picks up the ticket id from the
    contextvar, and short-circuits silently for non-MESA paths. We pass
    the iRODS session in so the project-detection walk has something to
    work with.
    """
    try:
        await record_avu_change(
            auth_value=auth,
            irods_path=project_path,
            target_type="collection",
            attribute=f"mesa.policy.{policy_name}",
            value="true",
            unit="",
            op="add" if enabled else "delete",
            tool_name=tool_name,
            session=session,
        )
    except DuckLakeMirrorError:
        # The iRODS-side change already succeeded; surfacing the mirror
        # failure would require a partial-failure envelope. For policy
        # toggles we treat the mirror as best-effort — the structured
        # tool result already records the policy-toggle outcome.
        return


@register_tool(
    "mesa_policy_enable",
    (
        "Enable a MESA policy on a project root collection by writing the "
        "``mesa.policy.<policy_name>=true`` AVU. Records the change into "
        "the project's DuckLake when MESA-enabled."
    ),
    input_model=PolicyToggleInput,
)
async def handle_policy_enable(
    args: PolicyToggleInput,
    *,
    auth_value: AuthValue | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    auth = auth_value or require_current_auth_value()
    if auth.is_anonymous():
        raise ToolError(
            code="forbidden",
            message="anonymous user is not allowed to toggle policies",
            details={"tool": "mesa_policy_enable"},
        )
    norm = assert_allowed(args.project_path, auth)
    sess = session or default_pool().get(auth)
    _assert_collection(sess, norm)
    result = policy_helpers.set_mesa_policy(sess, norm, args.policy_name, enabled=True)
    await _record_into_ducklake(
        project_path=norm,
        policy_name=args.policy_name,
        enabled=True,
        auth=auth,
        session=sess,
        tool_name="mesa_policy_enable",
    )
    return result


@register_tool(
    "mesa_policy_disable",
    (
        "Disable a MESA policy on a project root collection by removing the "
        "``mesa.policy.<policy_name>`` AVU. Records the change into the "
        "project's DuckLake when MESA-enabled."
    ),
    input_model=PolicyToggleInput,
)
async def handle_policy_disable(
    args: PolicyToggleInput,
    *,
    auth_value: AuthValue | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    auth = auth_value or require_current_auth_value()
    if auth.is_anonymous():
        raise ToolError(
            code="forbidden",
            message="anonymous user is not allowed to toggle policies",
            details={"tool": "mesa_policy_disable"},
        )
    norm = assert_allowed(args.project_path, auth)
    sess = session or default_pool().get(auth)
    _assert_collection(sess, norm)
    result = policy_helpers.set_mesa_policy(sess, norm, args.policy_name, enabled=False)
    await _record_into_ducklake(
        project_path=norm,
        policy_name=args.policy_name,
        enabled=False,
        auth=auth,
        session=sess,
        tool_name="mesa_policy_disable",
    )
    return result
