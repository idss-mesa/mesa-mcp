"""Individual ``ds_*`` tool implementations.

One module per tool, mirroring ``irods-mcp-server/irods/*.go``. New tool
modules are picked up automatically — drop a ``.py`` file in this
directory and its top-level ``@register_tool`` decorators fire on package
import.

This auto-discovery is intentional so the three ``ds_*`` porting tracks
(AVU tools, file/dir/ACL tools, tickets/rules/policies) can land their
files independently without racing on this ``__init__.py``.
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
