"""``ds_execute_rule`` — invoke an iRODS rule on the connected server.

Inputs are either a ``rule_name`` (a server-installed rule) **or**
``rule_text`` (an inline iRL snippet) — never both. The
``input_parameters`` dict is forwarded to the rule as ``*key=value``
bindings; any value that looks like an iRODS path (``/zone/...``) is
validated through :func:`mesa_mcp.irods.access.assert_allowed` so a rule
cannot be used as an access-control bypass.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import require_current_auth_value
from mesa_mcp.errors import ToolError
from mesa_mcp.irods import rules as rule_helpers
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool

DEFAULT_INSTANCE = "irods_rule_engine_plugin-irods_rule_language-instance"


class ExecuteRuleInput(BaseModel):
    """Input schema for ``ds_execute_rule``.

    Exactly one of ``rule_name`` / ``rule_text`` must be supplied.
    ``rule_name`` invokes a named rule from the server's rule base via
    a thin wrapper rule body; ``rule_text`` runs the supplied iRL
    fragment as-is.
    """

    rule_name: str | None = Field(
        default=None,
        description="Name of a server-installed rule to invoke.",
    )
    rule_text: str | None = Field(
        default=None,
        description="Inline iRL fragment to execute.",
    )
    input_parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Input parameters bound into the rule body.",
    )
    output_parameters: list[str] = Field(
        default_factory=list,
        description="Names of rule output parameters to return.",
    )
    instance_name: str = Field(
        default=DEFAULT_INSTANCE,
        description="Rule engine instance to target.",
    )

    @model_validator(mode="after")
    def _exactly_one_of(self) -> ExecuteRuleInput:
        if (self.rule_name is None) == (self.rule_text is None):
            raise ValueError("exactly one of rule_name or rule_text must be supplied")
        return self


def _looks_like_irods_path(value: Any) -> bool:
    """Heuristic: a value is a path candidate if it's a str that starts with '/'."""
    return isinstance(value, str) and value.startswith("/") and len(value) > 1


def _validate_input_paths(inputs: dict[str, Any], auth_value: AuthValue) -> None:
    """Path-check every iRODS-looking value in the input parameter dict."""
    for key, value in inputs.items():
        if _looks_like_irods_path(value):
            # ``assert_allowed`` raises ``ToolError(code='forbidden')`` on
            # rejection. We let it propagate.
            assert_allowed(value, auth_value)
            del key  # keep linters happy in tools that read both


@register_tool(
    "ds_execute_rule",
    (
        "Run an iRODS rule. Supply either rule_name (server-installed) or "
        "rule_text (inline iRL). Output parameters are returned as a dict; "
        "iRODS stdout/stderr are returned when output_parameters includes "
        "'ruleExecOut'. Path-typed input parameters are checked against the "
        "caller's accessible paths before the rule fires."
    ),
    input_model=ExecuteRuleInput,
)
async def handle_execute_rule(
    args: ExecuteRuleInput,
    *,
    auth_value: AuthValue | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    auth = auth_value or require_current_auth_value()
    _validate_input_paths(args.input_parameters, auth)

    sess = session or default_pool().get(auth)

    # ``rule_name`` is invoked through a small wrapper body — PRC has no
    # named-rule-invocation API of its own, but rules registered in the
    # server rule base are callable from an inline body that just calls
    # them. We pass each input parameter as a positional argument string.
    if args.rule_text is not None:
        body = args.rule_text
    else:
        if not args.rule_name:
            raise ToolError(
                code="invalid_argument",
                message="rule_name must be a non-empty string.",
            )
        param_args = ", ".join(f"*{key}" for key in args.input_parameters)
        body = f"{args.rule_name}({param_args});"

    try:
        result = rule_helpers.execute_rule(
            sess,
            body=body,
            input_parameters=args.input_parameters,
            output_parameters=args.output_parameters,
            instance_name=args.instance_name,
        )
    except Exception as exc:  # noqa: BLE001 - PRC raises a variety of types
        raise ToolError(
            code="irods_error",
            message=f"Rule execution failed: {exc}",
            details={
                "rule_name": args.rule_name,
                "instance_name": args.instance_name,
            },
        ) from exc

    return result
