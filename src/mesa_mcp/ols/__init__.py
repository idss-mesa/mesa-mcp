"""OBO Foundry / EMBL-EBI Ontology Lookup Service (OLS) integration.

This package hosts:

* :mod:`mesa_mcp.ols.client` — the :class:`OLSClient` HTTP wrapper (ported
  from ``cyverse/esiil-portal/portal/services/ols_client.py``, Django ``cache``
  swapped for :class:`cachetools.TTLCache`).
* :mod:`mesa_mcp.ols.transform` — pure AVU ↔ annotation transforms (ported
  verbatim from ``ols_transform.py``).
* :mod:`mesa_mcp.ols.tools` — individual ``mesa_ols_*`` and ``mesa_avu_*``
  MCP tools.

Importing this package is *the* registration trigger: the
``from .tools import …`` import below pulls in each tool module so the
``@register_tool`` decorators run and the global registry is populated.
"""

from __future__ import annotations

from .client import OLSClient, get_ols_client

__all__ = [
    "OLSClient",
    "get_ols_client",
    "get_default_client",
    "set_default_client",
]

# Module-level singleton. Lazily constructed on first access so tests can
# substitute a mock via ``set_default_client(...)`` before any tool runs.
_default_client: OLSClient | None = None


def get_default_client() -> OLSClient:
    """Return the process-wide :class:`OLSClient`, building one on first call.

    Tool handlers fetch the client through this accessor so a single instance
    is shared across all ``mesa_ols_*`` tools — that means the in-process TTL
    caches do useful work across calls. Tests can stub out the client by
    calling :func:`set_default_client` before invocation.
    """
    global _default_client
    if _default_client is None:
        _default_client = get_ols_client()
    return _default_client


def set_default_client(client: OLSClient | None) -> None:
    """Replace (or clear) the module-level singleton. Test-only injection point."""
    global _default_client
    _default_client = client


# Import the tools subpackage at the bottom so the @register_tool decorators
# fire as soon as ``mesa_mcp.ols`` is imported. Keep this import last to avoid
# circular-import surprises (each tool module imports from this package).
from . import tools as tools  # noqa: E402,F401  (registration side effect)
