"""Individual ``mesa_ducklake_*`` MCP tools.

One module per tool. Auto-discovery mirrors
``mesa_mcp.irods.tools.__init__``: drop a ``.py`` file here and its
top-level ``@register_tool`` decorators fire on package import.
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
