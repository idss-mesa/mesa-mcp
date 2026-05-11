"""AVU <-> Ontology Term Transformation.

Converts between flat iRODS AVUs (with ontology-specific prefixes like
``envo.*``, ``go.*``) and structured ontology annotations.

AVU convention::

    Attribute: <ontology_id>.<term_label_snake>  (e.g. envo.biome)
    Value:     User-entered text or selected term label
    Unit:      Term CURIE from OLS (e.g. ENVO:00000428)

Ported verbatim from ``cyverse/esiil-portal/portal/services/ols_transform.py``
— this module has no Django dependencies. The output shape is the canonical
AVU triple ``(attribute, value, unit)`` described in ``CLAUDE.md``; keeping
this contract identical to the portal's existing writer means AVUs emitted by
mesa-mcp and AVUs emitted by the portal are indistinguishable in iRODS.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Prefixes reserved by other schemas — never interpret these as OLS ontologies.
RESERVED_PREFIXES: frozenset[str] = frozenset(
    {
        "datacite",
        "dc",
        "eml",
        "ipc-",
        "irods::",
        "ipc_",
    }
)


def ontology_annotations_to_avus(
    ontology_id: str, annotations: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """Convert structured ontology annotations to flat AVUs.

    Parameters
    ----------
    ontology_id:
        Ontology identifier (e.g. ``"envo"``). Always lowercased on the way
        into the AVU attribute.
    annotations:
        List of dicts with ``"key"`` (snake_case), ``"value"``, and optional
        ``"curie"``.

    Returns
    -------
    list of dicts
        AVU triples with keys ``attribute``, ``value``, ``unit``.

    Example
    -------
    >>> ontology_annotations_to_avus('envo', [
    ...     {'key': 'biome', 'value': 'tropical moist broadleaf forest',
    ...      'curie': 'ENVO:00000428'},
    ... ])  # doctest: +ELLIPSIS
    [{'attribute': 'envo.biome', 'value': '...broadleaf forest', 'unit': 'ENVO:00000428'}]
    """
    prefix = ontology_id.lower()
    avus: list[dict[str, str]] = []
    for ann in annotations:
        key = (ann.get("key") or "").strip()
        value = (ann.get("value") or "").strip()
        if not key or not value:
            continue
        avus.append(
            {
                "attribute": f"{prefix}.{key}",
                "value": value,
                "unit": ann.get("curie", "") or "",
            }
        )
    return avus


def avus_to_ontology_annotations(
    ontology_id: str, avus: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """Extract AVUs for a specific ontology and return structured annotations.

    Reverses :func:`ontology_annotations_to_avus`.

    Parameters
    ----------
    ontology_id:
        Ontology identifier (e.g. ``"envo"``).
    avus:
        Full list of AVU dicts (with ``attribute``, ``value``, ``unit`` keys).

    Returns
    -------
    list of dicts
        Annotation dicts with ``key``, ``value``, ``curie``.
    """
    prefix = ontology_id.lower() + "."
    annotations: list[dict[str, str]] = []
    for avu in avus:
        attr = (avu.get("attribute") or "").lower()
        if attr.startswith(prefix):
            key = attr[len(prefix) :]
            if key:
                annotations.append(
                    {
                        "key": key,
                        "value": avu.get("value", ""),
                        "curie": avu.get("unit", ""),
                    }
                )
    return annotations


def extract_ontology_avus(
    avus: list[dict[str, Any]], ontology_id: str
) -> list[dict[str, Any]]:
    """Filter AVUs to only those belonging to a specific ontology prefix.

    Parameters
    ----------
    avus:
        Full list of AVUs.
    ontology_id:
        Ontology identifier.

    Returns
    -------
    list of dicts
        Filtered AVU dicts.
    """
    prefix = ontology_id.lower() + "."
    return [a for a in avus if (a.get("attribute") or "").lower().startswith(prefix)]


def detect_ontology_prefixes(
    avus: list[dict[str, Any]],
    known_ontology_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Detect OLS ontology prefixes present in existing AVUs.

    Scans AVUs for attributes matching the pattern ``<prefix>.<key>`` where
    ``<prefix>`` is not a reserved schema prefix. Optionally validates against
    a set of known ontology IDs.

    Parameters
    ----------
    avus:
        Full list of AVUs.
    known_ontology_ids:
        Optional set of valid ontology IDs to match against. If ``None``, any
        non-reserved prefix is returned.

    Returns
    -------
    list of dicts
        Each entry has ``ontologyId`` and ``count``. Sorted by ``count``
        descending so the most-used ontology surfaces first.
    """
    prefix_counts: dict[str, int] = {}

    for avu in avus:
        attr = (avu.get("attribute") or "").strip()
        if not attr or "." not in attr:
            continue

        prefix = attr.split(".", 1)[0].lower()

        # Skip reserved prefixes.
        if prefix in RESERVED_PREFIXES:
            continue
        # Skip system-style prefixes.
        if any(attr.lower().startswith(rp) for rp in ("ipc-", "irods::", "ipc_")):
            continue

        # If we have a known set, only count matches.
        if known_ontology_ids is not None and prefix not in known_ontology_ids:
            continue

        prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1

    return sorted(
        [{"ontologyId": k, "count": v} for k, v in prefix_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )
