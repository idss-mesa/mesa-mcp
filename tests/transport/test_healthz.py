"""Unit tests for the ``/healthz`` endpoint."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from mesa_mcp import __version__
from mesa_mcp.transport.healthz import healthz


def test_healthz_returns_200_with_status_and_version() -> None:
    app = Starlette(routes=[Route("/healthz", endpoint=healthz, methods=["GET"])])
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "version": __version__}


def test_healthz_within_full_sse_app_skips_auth(config_fixture) -> None:
    """``/healthz`` must work with OIDC mounted: it is the bypass-prefix."""
    from mesa_mcp.server import MesaServer
    from mesa_mcp.transport.sse import build_sse_app

    # Empty discovery URL -> no-OIDC mode. Use a configured discovery URL
    # below in test_sse_auth to exercise the real middleware path.
    config = config_fixture.model_copy(deep=True)
    config.server.oidc_discovery_url = ""
    server = MesaServer(config=config)
    app = build_sse_app(server, config)
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
