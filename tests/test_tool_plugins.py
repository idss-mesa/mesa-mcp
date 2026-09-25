"""Third-party tool packages register through ``mesa_mcp.tools`` entry points and may declare
their own ``_meta`` surface (register_tool(meta=...)); a broken plugin is skipped unless strict."""

from __future__ import annotations

from importlib.metadata import EntryPoint

import pytest
from pydantic import BaseModel

from mesa_mcp import server
from mesa_mcp.config import Config
from mesa_mcp.server import MesaServer, get_tool, load_plugins, register_tool


class _In(BaseModel):
    x: int = 1


@pytest.fixture
def clean_registry():
    saved = dict(server._REGISTRY)
    saved_loaded = dict(server._LOADED_PLUGINS)
    yield
    server._REGISTRY.clear()
    server._REGISTRY.update(saved)
    server._LOADED_PLUGINS.clear()
    server._LOADED_PLUGINS.update(saved_loaded)


def test_register_tool_meta_seeds_surface(clean_registry):
    @register_tool("zz_plugin_tool", "demo", input_model=_In, meta={"io.mesa/surface": "decision"})
    async def handle(args: _In) -> dict:
        return {"ok": True}

    assert get_tool("zz_plugin_tool").meta == {"io.mesa/surface": "decision"}
    defs = {t.name: t for t in MesaServer(config=Config())._tool_definitions()}
    assert defs["zz_plugin_tool"].meta["io.mesa/surface"] == "decision"
    assert defs["ds_ping"].meta["io.mesa/surface"] == "irods"  # prefix rule still applies


def test_entry_points_are_loaded_and_broken_ones_skipped(clean_registry, monkeypatch, caplog):
    calls: list[str] = []

    class _EP(EntryPoint):
        def load(self):  # type: ignore[override]
            calls.append(self.name)
            if self.name == "broken":
                raise ImportError("boom")
            return object()

    eps = [
        _EP(name="good", value="pkg.mod", group="mesa_mcp.tools"),
        _EP(name="broken", value="pkg.bad", group="mesa_mcp.tools"),
    ]
    monkeypatch.setattr("importlib.metadata.entry_points", lambda **kw: eps)
    status = load_plugins()
    # other entry points installed in this environment (e.g. mesa-anyjev's decide) may
    # already be present; only the two fakes are asserted
    assert {k: status[k] for k in ("good", "broken")} == {
        "good": "loaded",
        "broken": "failed: ImportError: boom",
    }
    assert calls == ["good", "broken"]
    # loaded plugins are not imported twice; failed ones are retried
    load_plugins()
    assert calls == ["good", "broken", "broken"]
    with pytest.raises(RuntimeError, match="broken"):
        load_plugins(strict=True)


def test_server_loads_plugins_on_construction(clean_registry, monkeypatch):
    seen: list[bool] = []
    monkeypatch.setattr(server, "load_plugins", lambda *, strict=False: seen.append(strict) or {})
    MesaServer(config=Config())
    assert seen == [False]
    cfg = Config()
    cfg.server.strict_plugins = True
    MesaServer(config=cfg)
    assert seen == [False, True]
