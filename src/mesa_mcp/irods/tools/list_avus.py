"""``ds_list_avus`` — list AVUs on a file, directory, resource, or user.

Ported from ``irods-mcp-server/irods/list_avus.go`` (the Go reference is the
spec). The wire-level shape is preserved byte-for-byte: input keys
``target_type`` (path|resource|user) and ``target``, output keys
``target_type``, ``target``, ``avus`` where each AVU is
``{id, attribute, value, unit}``.

Implementation notes:

* For ``target_type=path`` we use python-irodsclient's
  ``session.metadata.get(DataObject|Collection, path)`` after probing which
  the path is. ``data_object`` is tried first because tagging individual
  files is the common case.
* ``target_type=resource`` queries ``ResourceMeta``.
* ``target_type=user`` queries ``UserMeta``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._avu_helpers import list_avus_for_path, resolve_path_target
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class ListAvusInput(BaseModel):
    """Input schema for ``ds_list_avus``. Mirrors the Go ``ListAVUsInputArgs``."""

    target_type: Literal["path", "resource", "user"] = Field(
        ...,
        description=(
            "The type of the target to list AVU. It can be 'path', 'resource', "
            "or 'user'."
        ),
    )
    target: str = Field(
        ...,
        description=(
            "The target to list AVU. Path for 'path' target_type, resource name "
            "for 'resource' target_type, and user name for 'user' target_type."
        ),
    )


@register_tool(
    "ds_list_avus",
    "List AVUs (attribute-value-unit) from a file (data-object), directory "
    "(collection), resource, or user.",
    input_model=ListAvusInput,
)
async def handle_ds_list_avus(
    args: ListAvusInput,
    *,
    auth_value: AuthValue | None = None,
) -> dict[str, Any]:
    """Return AVUs attached to the target as a structured list."""
    if args.target_type == "path":
        if auth_value is None:
            raise ToolError(
                code="unauthenticated",
                message="ds_list_avus on a path requires an authenticated caller.",
            )
        norm = assert_allowed(args.target, auth_value)
        session = default_pool().get(auth_value)
        path_target = resolve_path_target(session, norm)
        avus = list_avus_for_path(session, norm, path_target)
        return {
            "target_type": "path",
            "target": norm,
            "avus": avus,
            "path_target_type": path_target,
        }

    if args.target_type == "resource":
        if auth_value is None:
            raise ToolError(
                code="unauthenticated",
                message="ds_list_avus requires an authenticated caller.",
            )
        session = default_pool().get(auth_value)
        avus = _list_resource_avus(session, args.target)
        return {"target_type": "resource", "target": args.target, "avus": avus}

    if args.target_type == "user":
        if auth_value is None:
            raise ToolError(
                code="unauthenticated",
                message="ds_list_avus requires an authenticated caller.",
            )
        session = default_pool().get(auth_value)
        avus = _list_user_avus(session, args.target, default_zone=auth_value.zone)
        return {"target_type": "user", "target": args.target, "avus": avus}

    raise ToolError(  # pragma: no cover - pydantic Literal blocks this
        code="invalid_argument",
        message=f"Unsupported target_type: {args.target_type!r}.",
        details={"target_type": args.target_type},
    )


def _list_resource_avus(session: Any, resource_name: str) -> list[dict[str, Any]]:
    from irods.models import Resource  # type: ignore[import-not-found]

    try:
        metas = session.metadata.get(Resource, resource_name)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="irods_error",
            message=f"Failed to list AVUs on resource {resource_name!r}: {exc}",
            details={"resource": resource_name},
        ) from exc
    return _meta_list_to_dicts(metas)


def _list_user_avus(
    session: Any,
    user_name: str,
    *,
    default_zone: str,
) -> list[dict[str, Any]]:
    from irods.models import User  # type: ignore[import-not-found]

    # iRODS user names can be passed as ``user#zone``. Match the Go behaviour.
    if "#" in user_name:
        user, _ = user_name.split("#", 1)
    else:
        user = user_name
    del default_zone  # not used by session.metadata.get(User, ...)

    try:
        metas = session.metadata.get(User, user)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="irods_error",
            message=f"Failed to list AVUs on user {user_name!r}: {exc}",
            details={"user": user_name},
        ) from exc
    return _meta_list_to_dicts(metas)


def _meta_list_to_dicts(metas: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in metas or []:
        out.append(
            {
                "id": getattr(m, "avu_id", None) or getattr(m, "id", None) or 0,
                "attribute": getattr(m, "name", ""),
                "value": getattr(m, "value", ""),
                "unit": getattr(m, "units", "") or "",
            }
        )
    return out
