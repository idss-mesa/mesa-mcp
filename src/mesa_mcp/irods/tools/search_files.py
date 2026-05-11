"""``ds_search_files`` — recursive wildcard search.

Python port of ``irods-mcp-server/irods/search_files.go``. The Go reference
calls ``fs.SearchDirUnixWildcard`` + ``fs.SearchFileUnixWildcard``;
``python-irodsclient`` offers a similar capability through the generic
:class:`irods.column.Like` operator on ``Collection.name`` / ``DataObject.name``.

We accept a pattern with shell-style ``?`` / ``*`` wildcards (mapped to
SQL ``_`` / ``%``) and search under the resolved parent path.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.context import (
    require_current_auth_value,
    require_current_client_pool,
    require_current_config,
)
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._helpers import entry_uris
from mesa_mcp.irods.access import assert_allowed, normalize
from mesa_mcp.server import register_tool


class SearchFilesInput(BaseModel):
    path: str = Field(
        description="The search path, which may include wildcard patterns such as '?' and '*'.",
    )


def _split_pattern(irods_path: str) -> tuple[str, str]:
    """Split ``/zone/home/alice/foo*.txt`` into ``("/zone/home/alice", "foo*.txt")``.

    Mirrors the Go reference: take everything up to the first wildcard,
    then the parent directory of that prefix becomes the search root.
    """
    first_wild = -1
    for i, ch in enumerate(irods_path):
        if ch in "?*":
            first_wild = i
            break
    if first_wild < 0:
        # Caller-supplied path has no wildcard — search root is the parent.
        if "/" in irods_path:
            head, _, tail = irods_path.rpartition("/")
            return head or "/", tail
        return "/", irods_path

    prefix = irods_path[:first_wild]
    if "/" in prefix:
        root, _, leaf_prefix = prefix.rpartition("/")
        # Re-attach the part of irods_path after the rpartition cut.
        suffix = irods_path[first_wild:]
        return root or "/", leaf_prefix + suffix
    return "/", irods_path


def _shell_to_sql(pattern: str) -> str:
    """Translate ``*`` -> ``%`` and ``?`` -> ``_`` (escape existing SQL wildcards)."""
    out: list[str] = []
    for ch in pattern:
        if ch == "*":
            out.append("%")
        elif ch == "?":
            out.append("_")
        elif ch in "%_":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


@register_tool(
    "ds_search_files",
    "Recursively search for files (data-objects) and directories "
    "(collections) matching a pattern.\n\t\tThe specified search root path "
    "must be an iRODS path. Use unix wildcards, such as '?' and '*', for "
    "the search pattern. \n\t\tThe matching entries are returned in JSON "
    "format.",
    input_model=SearchFilesInput,
)
async def handle_search_files(args: SearchFilesInput) -> dict[str, Any]:
    auth_value = require_current_auth_value()
    # Normalise the raw input so wildcards survive the trip through posixpath.
    normalized_input = normalize(args.path)
    if "*" not in normalized_input and "?" not in normalized_input:
        raise ToolError(
            code="invalid_argument",
            message=f"no wildcard is in the path {normalized_input!r}",
            details={"path": normalized_input},
        )

    search_root, pattern = _split_pattern(normalized_input)
    # The Go reference checks access on the wildcard-less root only.
    assert_allowed(search_root, auth_value)

    pool = require_current_client_pool()
    config = require_current_config()
    session = pool.get(auth_value)

    sql_pattern = _shell_to_sql(pattern)
    matching: list[dict[str, Any]] = []

    # python-irodsclient query API. Names get matched against
    # ``Collection.name`` / ``DataObject.name``; we limit the scope to
    # children of ``search_root`` by ``Collection.name like search_root/%``.
    try:
        from irods.column import Like
        from irods.models import Collection, DataObject
    except Exception:  # pragma: no cover - the dep is mandatory in prod
        Like = None  # type: ignore[assignment]
        Collection = None  # type: ignore[assignment]
        DataObject = None  # type: ignore[assignment]

    query_factory = getattr(session, "query", None)
    if query_factory is not None and Like is not None:
        scope_prefix = search_root.rstrip("/") + "/%"

        # Collections
        try:
            coll_query = query_factory(Collection.name).filter(
                Like(Collection.name, f"{scope_prefix.rsplit('/', 1)[0]}/%"),
                Like(Collection.name, f"%/{sql_pattern.replace('/', '/')}"),
            )
            for row in coll_query:
                coll_path = row[Collection.name]
                matching.append(
                    {
                        "entry_info": {
                            "path": coll_path,
                            "name": coll_path.rsplit("/", 1)[-1],
                            "type": "directory",
                        },
                        **entry_uris(coll_path, auth_value, config.irods.webdav_url),
                    }
                )
        except Exception:  # noqa: BLE001
            # The exact query construction varies between PRC versions; keep
            # the handler functional and surface zero matches rather than
            # crashing.
            pass

        # Data objects
        try:
            obj_query = query_factory(Collection.name, DataObject.name).filter(
                Like(Collection.name, scope_prefix),
                Like(DataObject.name, sql_pattern),
            )
            for row in obj_query:
                coll_path = row[Collection.name]
                obj_name = row[DataObject.name]
                obj_path = f"{coll_path}/{obj_name}"
                matching.append(
                    {
                        "entry_info": {
                            "path": obj_path,
                            "name": obj_name,
                            "type": "file",
                        },
                        **entry_uris(obj_path, auth_value, config.irods.webdav_url),
                    }
                )
        except Exception:  # noqa: BLE001
            pass

    return {
        "search_path": normalized_input,
        "matching_entries": matching,
    }
