"""Smoke tests for the mesa-mcp scaffold.

These tests prove the MCP plumbing without depending on the actual transport:
they instantiate :class:`mesa_mcp.server.MesaServer` and exercise the
in-process ``call`` path that the MCP SDK adapter delegates to. If these
pass, the registry, decorator, error path, and ``ds_ping`` handler are all
wired correctly.
"""

from __future__ import annotations

import pytest

from mesa_mcp import __version__
from mesa_mcp.errors import ToolError
from mesa_mcp.server import MesaServer, get_registered_tools


async def test_ds_ping_default_message(config_fixture):
    """``ds_ping`` with no arguments returns the literal 'ok' and the version."""
    server = MesaServer(config=config_fixture)
    result = await server.call("ds_ping", {})
    assert result == {"pong": "ok", "version": __version__}


async def test_ds_ping_echoes_message(config_fixture):
    """``ds_ping`` echoes a supplied message back as the ``pong`` field."""
    server = MesaServer(config=config_fixture)
    result = await server.call("ds_ping", {"message": "hello mesa"})
    assert result == {"pong": "hello mesa", "version": __version__}


async def test_unknown_tool_raises_tool_error(config_fixture):
    """Calling a tool that isn't registered should raise a structured ``ToolError``."""
    server = MesaServer(config=config_fixture)
    with pytest.raises(ToolError) as excinfo:
        await server.call("nope_not_a_tool")
    assert excinfo.value.code == "unknown_tool"


def test_registry_contains_ds_ping():
    """``ds_ping`` registers itself at import time."""
    names = {spec.name for spec in get_registered_tools()}
    assert "ds_ping" in names
