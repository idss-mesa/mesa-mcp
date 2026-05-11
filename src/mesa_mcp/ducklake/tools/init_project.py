"""``mesa_ducklake_init_project`` — enroll an iRODS collection in MESA.

Idempotent bootstrap for AVU-history tracking on a project root.
Performs the three steps the design calls out:

1. Ensure ``<irods_path>/.mesa/ducklake/`` collection exists.
2. Ensure ``mesa.enabled=true`` AVU is set on ``<irods_path>``.
3. Find-or-register the project in the Postgres catalog.

Each step is independently idempotent: re-running the tool on an
already-enrolled project is a no-op and returns the existing project
info. Errors from any step are surfaced as structured
:class:`ToolError`s with ``init_project_failed_*`` codes so MCP
clients can identify the failure stage.

Requires:

* mesa-ducklake installed (else ``ducklake_disabled``).
* ``Config.ducklake.catalog_dsn`` set (else ``ducklake_disabled``).
* Caller has write access to ``irods_path``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.ducklake.client import get_default_client
from mesa_mcp.errors import ToolError
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool

TOOL_NAME = "mesa_ducklake_init_project"

# AVU marker. Must match :mod:`mesa_ducklake.irods_path` and the
# detection logic in :func:`mesa_mcp.ducklake.client._collection_has_mesa_enabled`.
_MESA_ENABLED_ATTRIBUTE = "mesa.enabled"
_MESA_ENABLED_VALUE = "true"


class InitProjectInput(BaseModel):
    """Input schema for ``mesa_ducklake_init_project``."""

    irods_path: str = Field(
        ...,
        description=(
            "Absolute iRODS path of the project's root collection — the "
            "collection that will carry the ``mesa.enabled=true`` AVU and "
            "host the ``.mesa/ducklake/`` history sub-collection."
        ),
    )


@register_tool(
    TOOL_NAME,
    "Enroll an iRODS collection as a MESA project. Creates the "
    "<irods_path>/.mesa/ducklake/ sub-collection, sets the "
    "mesa.enabled=true AVU on the project root, and registers the "
    "project in the DuckLake catalog. Idempotent — safe to re-run.",
    input_model=InitProjectInput,
)
async def handle_mesa_ducklake_init_project(
    args: InitProjectInput,
    *,
    auth_value: AuthValue | None = None,
) -> dict[str, Any]:
    if auth_value is None:
        raise ToolError(
            code="unauthenticated",
            message=f"{TOOL_NAME} requires an authenticated caller.",
        )

    client = get_default_client()
    if client is None:
        raise ToolError(
            code="ducklake_disabled",
            message=(
                f"{TOOL_NAME} requires DuckLake. Set "
                "MESA_MCP_DUCKLAKE__CATALOG_DSN (or `ducklake.catalog_dsn` "
                "in config.yaml) and ensure the mesa-ducklake package is "
                "installed."
            ),
        )

    norm = assert_allowed(args.irods_path, auth_value)
    session = default_pool().get(auth_value)
    ducklake_path = f"{norm.rstrip('/')}/.mesa/ducklake"

    # Step 1 — project root must exist and be a collection. Per-step
    # ToolError codes so clients can pinpoint the failure.
    _ensure_project_root_is_collection(session, norm)

    # Step 2 — create the .mesa/ducklake/ sub-collection (idempotent).
    _ensure_ducklake_collection(session, ducklake_path)

    # Step 3 — set mesa.enabled=true on the project root (idempotent).
    _ensure_mesa_enabled_avu(session, norm)

    # Step 4 — find-or-register in the catalog (idempotent on path).
    project = _find_or_register_project(client, norm, auth_value)

    return {
        "project_id": str(project.project_id),
        "irods_path": project.irods_path,
        "irods_zone": project.irods_zone,
        "ducklake_path": project.ducklake_path,
        "created_at": project.created_at.isoformat(),
        "created_by": project.created_by,
        "status": project.status,
    }


# ---------------------------------------------------------------------------
# Helpers — each one isolates a failure stage so the ToolError code says
# *which* step blew up.
# ---------------------------------------------------------------------------


def _ensure_project_root_is_collection(session: Any, irods_path: str) -> None:
    from irods.exception import (  # type: ignore[import-not-found]
        CollectionDoesNotExist,
    )

    try:
        session.collections.get(irods_path)
    except CollectionDoesNotExist as exc:
        raise ToolError(
            code="init_project_failed_root_missing",
            message=(
                f"iRODS collection {irods_path!r} does not exist. Create "
                "it before calling mesa_ducklake_init_project."
            ),
            details={"irods_path": irods_path},
        ) from exc
    except Exception as exc:  # noqa: BLE001 - surface any PRC failure
        raise ToolError(
            code="init_project_failed_root_lookup",
            message=f"Failed to inspect {irods_path!r}: {exc}",
            details={"irods_path": irods_path},
        ) from exc


def _ensure_ducklake_collection(session: Any, ducklake_path: str) -> None:
    """Create ``<root>/.mesa/ducklake/``. Tolerates "already exists"."""
    try:
        session.collections.create(ducklake_path, recurse=True)
    except Exception as exc:  # noqa: BLE001 - PRC raises a mix of types
        msg = str(exc).lower()
        if "exist" in msg or "duplicate" in msg:
            return
        raise ToolError(
            code="init_project_failed_irods_create",
            message=(
                f"Failed to create DuckLake collection {ducklake_path!r}: {exc}"
            ),
            details={"ducklake_path": ducklake_path},
        ) from exc


def _ensure_mesa_enabled_avu(session: Any, irods_path: str) -> None:
    """Set ``mesa.enabled=true`` on ``irods_path``. Skip if already present."""
    from irods.meta import iRODSMeta  # type: ignore[import-not-found]
    from irods.models import Collection  # type: ignore[import-not-found]

    try:
        existing = session.metadata.get(Collection, irods_path)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="init_project_failed_avu_lookup",
            message=f"Failed to read AVUs on {irods_path!r}: {exc}",
            details={"irods_path": irods_path},
        ) from exc

    for meta in existing or []:
        name = getattr(meta, "name", "") or getattr(meta, "attribute", "")
        value = (getattr(meta, "value", "") or "").strip().lower()
        if name == _MESA_ENABLED_ATTRIBUTE and value in {
            _MESA_ENABLED_VALUE,
            "yes",
            "1",
        }:
            return

    try:
        session.metadata.add(
            Collection,
            irods_path,
            iRODSMeta(_MESA_ENABLED_ATTRIBUTE, _MESA_ENABLED_VALUE, ""),
        )
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="init_project_failed_avu_add",
            message=(
                f"Failed to add mesa.enabled=true AVU on {irods_path!r}: {exc}"
            ),
            details={"irods_path": irods_path},
        ) from exc


def _find_or_register_project(client: Any, irods_path: str, auth_value: AuthValue) -> Any:
    try:
        existing = client.find_project_by_path(irods_path)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="init_project_failed_catalog_lookup",
            message=f"DuckLake catalog lookup failed for {irods_path!r}: {exc}",
            details={"irods_path": irods_path},
        ) from exc

    if existing is not None:
        return existing

    try:
        return client.register_project(
            irods_path=irods_path,
            actor=auth_value.username,
            zone=auth_value.zone,
        )
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="init_project_failed_catalog_register",
            message=(
                f"DuckLake catalog register_project failed for {irods_path!r}: {exc}"
            ),
            details={"irods_path": irods_path},
        ) from exc
