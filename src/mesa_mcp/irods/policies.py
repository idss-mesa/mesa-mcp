"""iRODS Policy Composition Framework helpers and MESA-specific policy AVUs.

The iRODS Policy Composition Framework ("PCF") is server-side
configuration: policies are JSON snippets registered in
``server_config.json`` and the rule engine fires them at well-known
events. There is no PRC API that enumerates registered policies; the
configuration is not catalog-backed, so this module exposes a
best-effort stub plus a clearly-scoped MESA-specific policy surface
that uses AVUs on the project root collection.

MESA policies are toggled with the ``mesa.policy.<name>=true|false``
AVU pattern. ``mesa_policy_enable`` writes the AVU; ``mesa_policy_disable``
removes it (or rewrites it to ``false`` for auditability — we currently
delete to keep AVU listings clean).
"""

from __future__ import annotations

from typing import Any

from irods.meta import iRODSMeta
from irods.models import Collection

MESA_POLICY_PREFIX = "mesa.policy."


def list_pcf_policies(_session: Any) -> dict[str, Any]:
    """Return registered Policy Composition Framework policies.

    iRODS does not expose PCF state through PRC. The composition lives
    in ``server_config.json`` under the rule engine instances. To
    surface the policies a server has registered, install a custom
    server-side introspection rule and invoke it via ``ds_execute_rule``.
    """
    return {
        "policies": [],
        "note": (
            "Policy Composition introspection requires a server-side rule "
            "(see mesa-ducklake/irods-rules/); iRODS does not expose PCF "
            "state through python-irodsclient."
        ),
    }


def get_pcf_policy_config(_session: Any, policy_name: str) -> dict[str, Any]:
    """Return the configuration of a single PCF policy, or a stub.

    Same limitation as :func:`list_pcf_policies` — iRODS does not expose
    PCF config through PRC. The stub returns the policy name and a note
    so callers can switch on ``config is None``.
    """
    return {
        "name": policy_name,
        "config": None,
        "note": (
            "Policy Composition config is not exposed by PRC. Install a "
            "server-side introspection rule and call it via "
            "ds_execute_rule."
        ),
    }


def list_mesa_policies(session: Any, project_path: str) -> list[dict[str, Any]]:
    """Return the MESA-specific policy AVUs on a project root collection.

    .. note::

       **Not exposed as a tool.** ``ds_list_policies`` calls
       :func:`list_pcf_policies` (a stub that reports PCF config is not
       introspectable via PRC), so MESA's own ``mesa.policy.*`` AVUs —
       which this function reads and :func:`set_mesa_policy` writes — are
       unreachable over MCP. Exposing them is a small addition and
       probably what a caller asking about "policies" expects; it is
       recorded here rather than silently left dangling.

    Walks the AVUs whose attribute starts with ``mesa.policy.`` and
    returns ``{name, enabled, value}`` triples. Values other than
    ``"true"`` are reported with ``enabled=False`` so admins can tell
    when a policy AVU was written by something other than mesa-mcp.
    """
    avus = session.metadata.get(Collection, project_path)
    policies: list[dict[str, Any]] = []
    for avu in avus:
        attribute = getattr(avu, "name", None) or getattr(avu, "attribute", "")
        if not attribute or not attribute.startswith(MESA_POLICY_PREFIX):
            continue
        value = getattr(avu, "value", "")
        policies.append(
            {
                "name": attribute[len(MESA_POLICY_PREFIX) :],
                "value": value,
                "enabled": value == "true",
            },
        )
    return policies


def set_mesa_policy(
    session: Any,
    project_path: str,
    name: str,
    enabled: bool,
) -> dict[str, Any]:
    """Toggle a MESA-defined policy on a project root collection.

    The AVU is ``("mesa.policy.<name>", "true", "")``. Enabling sets
    the AVU (idempotently — duplicate adds are a no-op via
    delete-then-add). Disabling removes the AVU outright; we don't
    leave a ``=false`` row behind because the absence of the AVU is
    the canonical "disabled" state, matching how
    ``mesa.enabled`` works.
    """
    attribute = f"{MESA_POLICY_PREFIX}{name}"

    # Find any existing AVU rows with this attribute and remove them so
    # we don't end up with duplicate triples after a toggle cycle.
    existing = [
        avu
        for avu in session.metadata.get(Collection, project_path)
        if (getattr(avu, "name", None) or getattr(avu, "attribute", "")) == attribute
    ]
    for avu in existing:
        session.metadata.remove(Collection, project_path, avu)

    if enabled:
        session.metadata.add(Collection, project_path, iRODSMeta(attribute, "true", ""))

    return {
        "project_path": project_path,
        "policy": name,
        "enabled": enabled,
        "avu": {"attribute": attribute, "value": "true" if enabled else None},
    }
