"""Follow-ups from the dead-config sweep.

Three changes, each pinned here:

1. ``ds_list_policies`` reports MESA's own ``mesa.policy.*`` AVUs, not
   only the Policy Composition Framework stub.
2. ``ducklake.data_collection`` reaches the DuckLake client.
3. ``oauth2_client_secret`` is gone, and its removal is visible rather
   than silent — including via the environment, which is how operators
   were previously told to supply it.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.config import Config, ServerConfig, load_config
from mesa_mcp.errors import ToolError
from mesa_mcp.irods.tools.list_policies import (
    ListPoliciesInput,
    handle_list_policies,
)


@pytest.fixture
def auth() -> AuthValue:
    return AuthValue(
        username="alice", zone="iplant", password="pw", auth_scheme="native"
    )


class _Avu:
    def __init__(self, name: str, value: str) -> None:
        self.name, self.value, self.unit = name, value, ""


@pytest.fixture
def session() -> MagicMock:
    sess = MagicMock()
    sess.metadata.get.return_value = [
        _Avu("mesa.policy.require_orcid", "true"),
        _Avu("mesa.policy.embargo", "false"),
        _Avu("unrelated.attribute", "ignored"),
    ]
    return sess


# ---------------------------------------------------------------------------
# 1. ds_list_policies surfaces MESA policies
# ---------------------------------------------------------------------------


async def test_list_policies_reports_mesa_policies_for_a_project(auth, session):
    result = await handle_list_policies(
        ListPoliciesInput(project_path="/iplant/home/alice/proj"),
        auth_value=auth,
        session=session,
    )
    assert result["project_path"] == "/iplant/home/alice/proj"
    assert result["mesa_policies"] == [
        {"name": "require_orcid", "value": "true", "enabled": True},
        {"name": "embargo", "value": "false", "enabled": False},
    ]


async def test_list_policies_still_returns_the_pcf_envelope(auth, session):
    """The PCF stub must not disappear — clients may already read it."""
    result = await handle_list_policies(
        ListPoliciesInput(project_path="/iplant/home/alice/proj"),
        auth_value=auth,
        session=session,
    )
    assert "policies" in result
    assert "note" in result


async def test_list_policies_without_a_path_says_how_to_get_them(auth, session):
    result = await handle_list_policies(
        ListPoliciesInput(), auth_value=auth, session=session
    )
    assert result["mesa_policies"] is None
    assert "project_path" in result["mesa_policies_note"]


async def test_list_policies_access_checks_the_path(auth, session):
    """A policy listing reveals how a collection is governed."""
    with pytest.raises(ToolError) as err:
        await handle_list_policies(
            ListPoliciesInput(project_path="/otherzone/home/bob/secret"),
            auth_value=auth,
            session=session,
        )
    assert err.value.code == "forbidden"


async def test_list_policies_refuses_anonymous(session):
    anon = AuthValue(
        username="anonymous", zone="iplant", password=None, auth_scheme="anonymous"
    )
    with pytest.raises(ToolError) as err:
        await handle_list_policies(
            ListPoliciesInput(), auth_value=anon, session=session
        )
    assert err.value.code == "forbidden"


# ---------------------------------------------------------------------------
# 2. data_collection reaches the DuckLake client
# ---------------------------------------------------------------------------


def _capture_client_kwargs(monkeypatch, data_collection: str | None) -> dict:
    """Build the default DuckLake client and capture its constructor kwargs.

    ``get_default_client`` imports ``get_active_config`` and
    ``DuckLakeClient`` *inside* the function, so both are patched at
    their source modules rather than on ``mesa_mcp.ducklake.client``.
    """
    import sys

    from mesa_mcp import config as config_module
    from mesa_mcp.ducklake import client as dl

    captured: dict = {}

    class _FakeClient:
        # An explicit ``data_collection`` parameter, because the caller
        # inspects the signature before forwarding it — a bare **kwargs
        # fake would exercise the "unsupported" branch instead.
        def __init__(self, *, data_collection: str | None = None, **kwargs):
            captured.update(kwargs)
            if data_collection is not None:
                captured["data_collection"] = data_collection

    cfg = Config()
    cfg.ducklake.catalog_dsn = "duckdb:///tmp/probe.duckdb"
    if data_collection is not None:
        cfg.ducklake.data_collection = data_collection

    monkeypatch.setattr(dl, "_default_client", None, raising=False)
    monkeypatch.setattr(dl, "_default_client_initialised", False, raising=False)
    monkeypatch.setattr(config_module, "get_active_config", lambda: cfg)
    monkeypatch.setitem(
        sys.modules,
        "mesa_ducklake",
        type(sys)("mesa_ducklake"),
    )
    sys.modules["mesa_ducklake"].DuckLakeClient = _FakeClient  # type: ignore[attr-defined]

    dl.get_default_client()
    # Reset so the patched singleton does not leak into later tests.
    dl._default_client = None
    dl._default_client_initialised = False
    return captured


def test_data_collection_is_forwarded_to_the_ducklake_client(monkeypatch):
    captured = _capture_client_kwargs(monkeypatch, "_history")
    assert captured.get("data_collection") == "_history"


def test_default_data_collection_is_not_forwarded(monkeypatch):
    """Only a non-default value is sent, so an older mesa-ducklake pin
    that lacks the keyword keeps working."""
    captured = _capture_client_kwargs(monkeypatch, None)
    assert "data_collection" not in captured
    # The rest of the wiring must still be intact.
    assert captured["catalog_dsn"] == "duckdb:///tmp/probe.duckdb"


# ---------------------------------------------------------------------------
# 3. oauth2_client_secret is removed, and visibly so
# ---------------------------------------------------------------------------


def test_client_secret_field_is_gone():
    assert "oauth2_client_secret" not in ServerConfig.model_fields


def test_client_secret_in_yaml_warns(tmp_path, caplog):
    path = tmp_path / "config.yaml"
    path.write_text("server:\n  oauth2_client_secret: hunter2\n")
    with caplog.at_level(logging.WARNING):
        load_config(path)
    assert "oauth2_client_secret" in caplog.text


def test_client_secret_in_env_warns(caplog):
    """Operators were told to inject it via the environment, so the env
    layer must warn too — a silent drop there is the likelier case."""
    with caplog.at_level(logging.WARNING):
        load_config(env={"MESA_MCP_SERVER__OAUTH2_CLIENT_SECRET": "hunter2"})
    assert "oauth2_client_secret" in caplog.text


def test_the_warning_never_logs_the_secret_value(caplog):
    with caplog.at_level(logging.WARNING):
        load_config(env={"MESA_MCP_SERVER__OAUTH2_CLIENT_SECRET": "SUPERSECRET"})
    assert "SUPERSECRET" not in caplog.text


def test_valid_server_settings_still_load(caplog):
    with caplog.at_level(logging.WARNING):
        config = load_config(
            env={"MESA_MCP_SERVER__OIDC_AUDIENCE": "https://mesa-mcp.example.org"}
        )
    assert config.server.oidc_audience == "https://mesa-mcp.example.org"
    assert "unknown key" not in caplog.text
