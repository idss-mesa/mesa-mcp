"""iRODS Rule Engine helpers.

``python-irodsclient`` exposes rule execution through
:class:`irods.rule.Rule`. The helper here builds a ``Rule`` instance,
executes it, and unpacks the resulting ``MsParamArray`` into a plain
dict of output-parameter names to string values, which is the shape
mesa-mcp's ``ds_execute_rule`` returns.

Rule introspection (listing available rules, reading a rule's source)
is **not** a first-class PRC API — see :func:`list_rules` and
:func:`get_rule_definition` for the limitations.
"""

from __future__ import annotations

from typing import Any

from irods.rule import Rule


def _normalise_params(params: dict[str, Any] | None) -> dict[str, str]:
    """Coerce dict values to strings for the rule input parameter array.

    PRC's ``Rule`` stuffs every input parameter into a ``STR_PI`` slot,
    so non-string values would crash inside the message marshaller.
    We coerce here (str()) so callers can pass ints/floats naturally.
    """
    if not params:
        return {}
    return {key: str(value) for key, value in params.items()}


def execute_rule(
    session: Any,
    *,
    body: str | None = None,
    rule_file: str | None = None,
    input_parameters: dict[str, Any] | None = None,
    output_parameters: list[str] | None = None,
    instance_name: str | None = None,
) -> dict[str, Any]:
    """Run a rule against the connected iRODS server.

    Either ``body`` *or* ``rule_file`` must be supplied (not both). The
    return value mirrors what ``irule`` prints: ``{"output": {name:
    value, ...}, "stdout": "...", "stderr": "..."}``. ``stdout``/
    ``stderr`` are populated when ``output_parameters`` includes
    ``ruleExecOut``.
    """
    if body is None and rule_file is None:
        raise ValueError("execute_rule requires either body or rule_file")
    if body is not None and rule_file is not None:
        raise ValueError("execute_rule accepts only one of body/rule_file")

    output_str = ",".join(output_parameters) if output_parameters else ""

    rule = Rule(
        session,
        body=body or "",
        rule_file=rule_file,
        params=_normalise_params(input_parameters),
        output=output_str,
        instance_name=instance_name,
    )

    # Don't tear down the shared session — the caller's session is pooled.
    result = rule.execute(session_cleanup=False)

    out_params: dict[str, str] = {}
    stdout = ""
    stderr = ""

    # ``MsParamArray.MsParam_PI`` is the list of returned parameters in
    # the same order they appeared in ``output_parameters``.
    raw_params = getattr(result, "MsParam_PI", None) or []
    for ms_param in raw_params:
        label = getattr(ms_param, "label", "") or ""
        inout = getattr(ms_param, "inOutStruct", None)
        # ``ruleExecOut`` parameter carries stdoutBuf and stderrBuf,
        # other STR_PI parameters carry .myStr.
        if label == "ruleExecOut":
            stdout = _decode_exec_buffer(getattr(inout, "stdoutBuf", None))
            stderr = _decode_exec_buffer(getattr(inout, "stderrBuf", None))
        else:
            value = getattr(inout, "myStr", None)
            out_params[label] = value if value is not None else ""

    return {"output": out_params, "stdout": stdout, "stderr": stderr}


def _decode_exec_buffer(buf: Any) -> str:
    """Decode an iRODS ``ExecCmdOut`` buffer into a Python string."""
    if buf is None:
        return ""
    raw = getattr(buf, "buf", buf)
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace").rstrip("\x00")
    if isinstance(raw, str):
        return raw.rstrip("\x00")
    return str(raw)


def list_rules(session: Any) -> dict[str, Any]:
    """List rules visible to the user via the iRODS catalog.

    The iRODS server does not expose a first-class "list named rules"
    API through PRC. The ICAT has a ``RULE_EXEC_*`` set of columns that
    enumerates *delayed* rule executions, but not the rule base itself.

    Best-effort behaviour: enumerate delayed rule executions when
    available, otherwise return an empty list with a ``note`` field that
    explains the limitation. Server admins can install a custom rule
    that surfaces the rule base via ``ds_execute_rule`` if they need
    that surface.
    """
    rules: list[dict[str, Any]] = []
    note: str | None = None

    try:
        # PRC exposes a ``RuleExec`` model for delayed/queued rules. Try
        # it through getattr to stay forward-compatible with PRC versions
        # that don't ship it.
        from irods.models import RuleExec  # type: ignore[attr-defined]

        for row in session.query(RuleExec):
            rules.append(
                {
                    "id": row[RuleExec.id],
                    "name": row[RuleExec.name],
                    "frequency": row.get(RuleExec.frequency, ""),
                    "last_exec_time": row.get(RuleExec.last_exec_time, ""),
                    "rei_file_path": row.get(RuleExec.rei_file_path, ""),
                },
            )
    except Exception as exc:  # pragma: no cover - server-dependent
        note = (
            "iRODS does not expose its rule base over the catalog; only "
            "delayed/queued rules are listable, and even that requires "
            "server support. Underlying error: "
            f"{type(exc).__name__}"
        )

    if not rules and note is None:
        note = (
            "No delayed rules currently registered. iRODS does not expose "
            "the static rule base through PRC; install a custom rule on "
            "the server (e.g. msiRuleListing) and invoke it via "
            "ds_execute_rule to enumerate the rule base."
        )

    return {"rules": rules, "note": note}


def get_rule_definition(session: Any, rule_name: str) -> dict[str, Any]:
    """Return the source of a named rule.

    iRODS does not expose rule source code through PRC. The rule base
    lives on the server filesystem (typically ``/etc/irods/core.re`` or
    the configured rule directories) and is not catalog-backed. We
    return a stub result that documents the limitation; admins can wire
    an introspection rule on the server and call it through
    ``ds_execute_rule`` to satisfy this need.
    """
    return {
        "name": rule_name,
        "definition": None,
        "note": (
            "iRODS does not expose rule source over PRC. The rule base "
            "lives in the server's filesystem (e.g. /etc/irods/core.re) "
            "and is not catalog-backed. Admins can install a custom "
            "introspection rule and invoke it via ds_execute_rule."
        ),
    }
