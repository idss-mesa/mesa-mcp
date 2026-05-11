"""Individual ``mesa_ols_*`` and ``mesa_avu_*`` tool implementations.

Each submodule registers exactly one tool via the ``@register_tool``
decorator in :mod:`mesa_mcp.server`. Tool modules are picked up
automatically — drop a ``.py`` file in this directory and its
``@register_tool`` decorators fire on package import.

This auto-discovery is intentional so multiple agents can add tool
modules in parallel without racing on this ``__init__.py``.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

_PACKAGE_PATH = Path(__file__).parent

for _module_info in pkgutil.iter_modules([str(_PACKAGE_PATH)]):
    if _module_info.name.startswith("_"):
        continue
    importlib.import_module(f"{__name__}.{_module_info.name}")

del importlib, pkgutil, Path, _PACKAGE_PATH
