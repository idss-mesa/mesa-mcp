"""Internal helpers shared by the AVU ``ds_*`` tools.

These helpers wrap the few python-irodsclient calls that every AVU tool
needs (resolve a path to a ``DataObject`` vs ``Collection``, add an AVU,
delete an AVU). Keeping them in one place means ``ds_add_avu``,
``ds_delete_avu``, and the composite ``mesa_avu_apply_term`` tool all go
through one code path; the iRODS-side semantics of "what does it mean to
add an AVU" lives here once.
"""

from __future__ import annotations

from typing import Any, Literal

from mesa_mcp.errors import ToolError

# ``target_type`` for the path-based AVU tools. ``user`` and ``resource``
# AVUs (which the Go reference also supports) don't go through this helper
# — the tool handlers branch directly to ``session.metadata.add`` against
# the matching SQL model for those.
PathTargetType = Literal["data_object", "collection"]


def resolve_path_target(
    session: Any,
    path: str,
    *,
    hint: str | None = None,
) -> PathTargetType:
    """Decide whether ``path`` is a data object or a collection.

    Parameters
    ----------
    session:
        An authenticated ``iRODSSession``.
    path:
        Normalised iRODS logical path.
    hint:
        Optional caller-supplied hint (``"data_object"`` or ``"collection"``).
        When supplied the function only verifies the path exists as that
        type; otherwise it tries ``data_objects.get`` first and falls back
        to ``collections.get``.

    Returns
    -------
    str
        Either ``"data_object"`` or ``"collection"``.

    Raises
    ------
    ToolError
        ``not_found`` when the path doesn't exist as either, or as the
        hinted type. ``invalid_argument`` when the hint is unrecognised.
    """
    # Local imports keep module import cheap when these aren't needed (and
    # let tests stub the session without dragging the real exception
    # classes in).
    from irods.exception import (  # type: ignore[import-not-found]
        CollectionDoesNotExist,
        DataObjectDoesNotExist,
    )

    if hint not in (None, "data_object", "collection"):
        raise ToolError(
            code="invalid_argument",
            message=f"Unsupported target_type hint: {hint!r}.",
            details={"hint": hint, "expected": ["data_object", "collection"]},
        )

    if hint == "data_object":
        try:
            session.data_objects.get(path)
        except (DataObjectDoesNotExist, FileNotFoundError) as exc:
            raise ToolError(
                code="not_found",
                message=f"Data object {path!r} does not exist.",
                details={"path": path},
            ) from exc
        return "data_object"

    if hint == "collection":
        try:
            session.collections.get(path)
        except (CollectionDoesNotExist, FileNotFoundError) as exc:
            raise ToolError(
                code="not_found",
                message=f"Collection {path!r} does not exist.",
                details={"path": path},
            ) from exc
        return "collection"

    # No hint: try data object first (the common case for AVU writes is
    # tagging individual files), then fall back to collection.
    try:
        session.data_objects.get(path)
        return "data_object"
    except (DataObjectDoesNotExist, FileNotFoundError):
        pass
    except Exception:  # noqa: BLE001 - python-irodsclient raises various
        pass

    try:
        session.collections.get(path)
        return "collection"
    except (CollectionDoesNotExist, FileNotFoundError) as exc:
        raise ToolError(
            code="not_found",
            message=f"Path {path!r} does not exist as either a data object or a collection.",
            details={"path": path},
        ) from exc


def _model_class_for_target(target_type: PathTargetType) -> Any:
    """Return the iRODS ORM model class matching ``target_type``."""
    from irods.models import Collection, DataObject  # type: ignore[import-not-found]

    if target_type == "data_object":
        return DataObject
    if target_type == "collection":
        return Collection
    raise ToolError(  # pragma: no cover - defensive
        code="invalid_argument",
        message=f"Unsupported target_type: {target_type!r}.",
        details={"target_type": target_type},
    )


def add_avu_to_irods(
    session: Any,
    path: str,
    target_type: PathTargetType,
    avu: dict[str, str],
) -> dict[str, str]:
    """Add one AVU to a data object or collection.

    Parameters
    ----------
    session:
        An authenticated ``iRODSSession``.
    path:
        Normalised iRODS logical path.
    target_type:
        ``"data_object"`` or ``"collection"``.
    avu:
        Dict with keys ``attribute``, ``value``, optional ``unit``.

    Returns
    -------
    dict
        The AVU as written, with keys ``attribute``, ``value``, ``unit``.

    Raises
    ------
    ToolError
        ``invalid_argument`` for missing required AVU fields, ``irods_error``
        when the underlying ``session.metadata.add`` call fails.
    """
    from irods.meta import iRODSMeta  # type: ignore[import-not-found]

    attribute = (avu.get("attribute") or "").strip()
    value = (avu.get("value") or "").strip()
    unit = (avu.get("unit") or "").strip()

    if not attribute or not value:
        raise ToolError(
            code="invalid_argument",
            message="AVU 'attribute' and 'value' are required and non-empty.",
            details={"avu": avu},
        )

    model = _model_class_for_target(target_type)
    try:
        session.metadata.add(model, path, iRODSMeta(attribute, value, unit))
    except Exception as exc:  # noqa: BLE001 - python-irodsclient raises many
        raise ToolError(
            code="irods_error",
            message=f"Failed to add AVU to {path!r}: {exc}",
            details={
                "path": path,
                "target_type": target_type,
                "attribute": attribute,
                "value": value,
                "unit": unit,
            },
        ) from exc

    return {"attribute": attribute, "value": value, "unit": unit}


def delete_avu_from_irods(
    session: Any,
    path: str,
    target_type: PathTargetType,
    avu: dict[str, str],
) -> dict[str, str]:
    """Remove one AVU from a data object or collection.

    Mirrors :func:`add_avu_to_irods`. Raises ``ToolError(irods_error)`` if
    the underlying ``session.metadata.remove`` call fails (which includes
    "no such AVU" — the iRODS server signals that by raising).
    """
    from irods.meta import iRODSMeta  # type: ignore[import-not-found]

    attribute = (avu.get("attribute") or "").strip()
    value = (avu.get("value") or "").strip()
    unit = (avu.get("unit") or "").strip()

    if not attribute:
        raise ToolError(
            code="invalid_argument",
            message="AVU 'attribute' is required for deletion.",
            details={"avu": avu},
        )

    model = _model_class_for_target(target_type)
    try:
        session.metadata.remove(model, path, iRODSMeta(attribute, value, unit))
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="irods_error",
            message=f"Failed to delete AVU from {path!r}: {exc}",
            details={
                "path": path,
                "target_type": target_type,
                "attribute": attribute,
                "value": value,
                "unit": unit,
            },
        ) from exc

    return {"attribute": attribute, "value": value, "unit": unit}


def list_avus_for_path(
    session: Any,
    path: str,
    target_type: PathTargetType,
) -> list[dict[str, Any]]:
    """Return all AVUs on a data object or collection as triples + id."""
    model = _model_class_for_target(target_type)
    try:
        metas = session.metadata.get(model, path)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="irods_error",
            message=f"Failed to list AVUs on {path!r}: {exc}",
            details={"path": path, "target_type": target_type},
        ) from exc

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
