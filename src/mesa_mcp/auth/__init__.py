"""Authentication primitives for mesa-mcp.

This package mirrors the Go reference implementation in
``irods-mcp-server/common/auth.go`` and friends: a single :class:`AuthValue`
carries everything a tool handler needs to know about the caller, and small
extractor functions build an :class:`AuthValue` from the active transport
(stdio env vars today, HTTP headers later).

The :func:`build_account` bridge in :mod:`mesa_mcp.auth.irods_auth` translates
an :class:`AuthValue` into a ``python-irodsclient`` ``iRODSAccount``, which the
client pool (:mod:`mesa_mcp.irods.client_pool`) uses to open real sessions.
"""

from __future__ import annotations

from .extract import extract_from_env, extract_from_headers, resolve_credentials
from .irods_auth import build_account
from .irods_env import (
    extract_from_irods_env_file,
    load_irods_environment,
    load_irods_password,
)
from .models import AuthValue

__all__ = [
    "AuthValue",
    "build_account",
    "extract_from_env",
    "extract_from_headers",
    "extract_from_irods_env_file",
    "load_irods_environment",
    "load_irods_password",
    "resolve_credentials",
]
