"""CLI entry point for ``mesa-mcp``.

Parses command-line flags, loads configuration with the documented
``flag > env > YAML > defaults`` precedence, configures logging, and dispatches
to :func:`mesa_mcp.server.run`.

This module is intentionally thin: heavy lifting (transport selection, tool
registration) lives in ``mesa_mcp.server``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level ``argparse`` parser for ``mesa-mcp``."""
    parser = argparse.ArgumentParser(
        prog="mesa-mcp",
        description=(
            "MCP server bridging CyVerse iRODS, OBO/OLS ontology services, "
            "and DuckLake metadata history."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to a YAML config file. Overridden by environment variables "
        "(prefix MESA_MCP_) and by explicit command-line flags.",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse"),
        default=None,
        help="Transport to bind. Defaults to 'stdio' unless set elsewhere.",
    )
    parser.add_argument(
        "--log-level",
        choices=("debug", "info", "warning", "error", "critical"),
        default=None,
        help="Logging verbosity. Defaults to 'info' unless set elsewhere.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"mesa-mcp {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Returns an exit code suitable for ``sys.exit``. Importable so tests and
    embedders can drive it without ``subprocess``.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # Imports are deferred so that --help / --version work without pulling in
    # the heavy MCP, iRODS, and DuckLake dependency graphs.
    from .config import load_config, set_active_config
    from .logging import setup_logging
    from .server import run

    flag_overrides = {
        "transport": args.transport,
        "log_level": args.log_level,
    }
    flag_overrides = {k: v for k, v in flag_overrides.items() if v is not None}

    config = load_config(args.config, flag_overrides=flag_overrides)
    set_active_config(config)
    setup_logging(config.server.log_level, transport=config.server.transport)
    run(config, transport=config.server.transport)
    return 0


if __name__ == "__main__":  # pragma: no cover - module-as-script entrypoint
    sys.exit(main())
