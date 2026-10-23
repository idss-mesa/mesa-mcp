"""set_active_config / get_active_config + get_default_client honoring it."""

import importlib.util

import pytest

import mesa_mcp.ducklake.client as dl_client
from mesa_mcp.config import (
    Config,
    DuckLakeConfig,
    get_active_config,
    load_config,
    set_active_config,
)


def test_get_active_config_returns_the_set_config():
    cfg = Config(ducklake=DuckLakeConfig(catalog_dsn="duckdb:///tmp/x.duckdb"))
    set_active_config(cfg)
    try:
        assert get_active_config() is cfg
        assert get_active_config().ducklake.catalog_dsn == "duckdb:///tmp/x.duckdb"
    finally:
        set_active_config(None)


def test_get_active_config_falls_back_without_active():
    set_active_config(None)
    cfg = get_active_config()
    # Falls back to load_config() (env + defaults); catalog_dsn defaults to None.
    assert isinstance(cfg, Config)


requires_mesa_ducklake = pytest.mark.skipif(
    importlib.util.find_spec("mesa_ducklake") is None,
    reason="requires the optional 'ducklake' extra (pip install mesa-mcp[ducklake])",
)


@requires_mesa_ducklake
@pytest.mark.parametrize("suffix", ["", "?storage_version=v1.5.0"])
def test_get_default_client_reads_catalog_dsn_from_active_config(tmp_path, suffix):
    dsn = f"duckdb:///{tmp_path / 'cat.duckdb'}{suffix}"
    set_active_config(Config(ducklake=DuckLakeConfig(catalog_dsn=dsn)))
    dl_client.reset_default_client()
    try:
        client = dl_client.get_default_client()
        assert client is not None  # DuckLake now ENABLED from config (was None before the fix)
        assert type(client).__name__ == "DuckLakeClient"
    finally:
        dl_client.set_default_client(None)
        set_active_config(None)


def test_get_default_client_none_when_active_config_has_no_dsn():
    set_active_config(Config(ducklake=DuckLakeConfig(catalog_dsn=None)))
    dl_client.reset_default_client()
    try:
        assert dl_client.get_default_client() is None  # disabled — no dsn
    finally:
        dl_client.set_default_client(None)
        set_active_config(None)


def test_quack_catalog_dsn_loads_from_env():
    cfg = load_config(env={"MESA_MCP_DUCKLAKE__CATALOG_DSN": "quack://catalog-host:9494"})
    assert cfg.ducklake.catalog_dsn == "quack://catalog-host:9494"


@requires_mesa_ducklake
def test_get_default_client_accepts_a_quack_dsn():
    # mesa-ducklake opens the catalog lazily, so a quack:// DSN yields an
    # enabled client without a server; the facade must pass it through.
    from mesa_ducklake.catalog import catalog_backend

    dsn = "quack://localhost:9494"
    assert catalog_backend(dsn) == "quack"
    set_active_config(Config(ducklake=DuckLakeConfig(catalog_dsn=dsn)))
    dl_client.reset_default_client()
    try:
        client = dl_client.get_default_client()
        assert client is not None
        assert type(client).__name__ == "DuckLakeClient"
    finally:
        dl_client.set_default_client(None)
        set_active_config(None)
