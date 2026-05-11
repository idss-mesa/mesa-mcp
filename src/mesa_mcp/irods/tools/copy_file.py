"""``ds_copy_file`` — copy a data object or collection.

Python port of ``irods-mcp-server/irods/copy_file.go``.

``python-irodsclient`` does not expose a single ``CopyFileToFile``
equivalent — we re-implement the recursion ourselves: stat the source,
``open(src, 'r')`` + ``open(dst, 'w')`` for files, ``collections.create``
plus recursive walk for directories. This deliberately mirrors the Go
reference's recursion structure so the output ``source_entry_info_list``
and ``copied_entry_info_list`` come out in the same order: source first,
then breadth-first children.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.context import (
    require_current_auth_value,
    require_current_client_pool,
)
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._helpers import (
    entry_info,
    reject_anonymous_write,
    resolve_target,
)
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.server import register_tool

_COPY_CHUNK = 256 * 1024  # 256KB — keeps memory bounded for large objects.


class CopyFileInput(BaseModel):
    source_path: str = Field(
        description=(
            "The path to the source file (data-object) or directory "
            "(collection). If directory path is given, the entire directory "
            "and its contents will be copied."
        ),
    )
    destination_path: str = Field(
        description=(
            "The new, complete path to copy the file (data-object) or "
            "directory (collection) to, including its new name. The path "
            "must not already exist."
        ),
    )


def _copy_data_object(session: Any, src_path: str, dst_path: str) -> None:
    """Stream-copy a data object from ``src_path`` to ``dst_path``."""
    with session.data_objects.open(src_path, "r") as fp_src:
        with session.data_objects.open(dst_path, "w") as fp_dst:
            while True:
                chunk = fp_src.read(_COPY_CHUNK)
                if not chunk:
                    break
                fp_dst.write(chunk)


def _copy_recursive(
    session: Any,
    src_kind: str,
    src_model: Any,
    src_path: str,
    dst_path: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Recursive copy returning (source-entries, copied-entries) in order.

    Mirrors ``copy_file.go``'s ``copyFileInternal`` traversal: depth-first
    with the parent entry recorded before the children.
    """
    source_entries: list[dict[str, Any]] = [entry_info(src_model, src_kind)]

    if src_kind == "data_object":
        _copy_data_object(session, src_path, dst_path)
        dst_kind, dst_model = resolve_target(session, dst_path)
        return source_entries, [entry_info(dst_model, dst_kind)]

    # Collection: create destination, then recurse into each child.
    session.collections.create(dst_path)
    dst_kind, dst_model = resolve_target(session, dst_path)
    copied_entries: list[dict[str, Any]] = [entry_info(dst_model, dst_kind)]

    for child_coll in getattr(src_model, "subcollections", []) or []:
        child_name = getattr(child_coll, "name", None) or getattr(
            child_coll,
            "path",
            "",
        ).rsplit("/", 1)[-1]
        child_src_path = getattr(child_coll, "path", None)
        if not child_src_path:
            continue
        child_dst_path = f"{dst_path}/{child_name}"
        sub_src, sub_copied = _copy_recursive(
            session,
            "collection",
            child_coll,
            child_src_path,
            child_dst_path,
        )
        source_entries.extend(sub_src)
        copied_entries.extend(sub_copied)

    for child_obj in getattr(src_model, "data_objects", []) or []:
        child_name = getattr(child_obj, "name", None) or getattr(
            child_obj,
            "path",
            "",
        ).rsplit("/", 1)[-1]
        child_src_path = getattr(child_obj, "path", None)
        if not child_src_path:
            continue
        child_dst_path = f"{dst_path}/{child_name}"
        sub_src, sub_copied = _copy_recursive(
            session,
            "data_object",
            child_obj,
            child_src_path,
            child_dst_path,
        )
        source_entries.extend(sub_src)
        copied_entries.extend(sub_copied)

    return source_entries, copied_entries


@register_tool(
    "ds_copy_file",
    "Copy a file (data-object) or directory (collection) to a new location.",
    input_model=CopyFileInput,
)
async def handle_copy_file(args: CopyFileInput) -> dict[str, Any]:
    auth_value = require_current_auth_value()
    reject_anonymous_write(auth_value, "ds_copy_file")
    src_normalized = assert_allowed(args.source_path, auth_value)
    dst_normalized = assert_allowed(args.destination_path, auth_value)

    pool = require_current_client_pool()
    session = pool.get(auth_value)

    src_kind, src_model = resolve_target(session, src_normalized)

    try:
        source_entries, copied_entries = _copy_recursive(
            session,
            src_kind,
            src_model,
            src_normalized,
            dst_normalized,
        )
    except ToolError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="internal_error",
            message=(
                f"failed to copy file (data-object) or directory "
                f"(collection) from {src_normalized!r} to {dst_normalized!r}"
            ),
            details={
                "source_path": src_normalized,
                "destination_path": dst_normalized,
                "cause": str(exc),
            },
        ) from exc

    return {
        "source_path": src_normalized,
        "destination_path": dst_normalized,
        "source_entry_info_list": source_entries,
        "copied_entry_info_list": copied_entries,
    }
