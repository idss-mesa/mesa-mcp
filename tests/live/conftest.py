"""Fixtures for the live tier.

Gating (all env-driven, see ``docs/dev/testing.md``):

* ``MESA_LIVE=1``            — run tests marked ``live`` (real OLS traffic).
* ``MESA_LLM_API_KEY=…``     — additionally run tests marked ``llm`` (the
                              local vLLM models via the LiteLLM gateway).

Without those, every test in this directory is *skipped*, not deselected,
so ``pytest -q`` stays green and hermetic and the skip reasons show up in
the ``-ra`` summary.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest

import mesa_mcp.ols  # noqa: F401  (registers the mesa_ols_* tools)
from mesa_mcp.config import Config
from mesa_mcp.context import current_config
from mesa_mcp.ols import set_default_client
from mesa_mcp.server import MesaServer

from ._llm import LiveSettings, LLMClient, TokenLedger, ToolAgent, load_settings

# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------

_SETTINGS = load_settings()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    here = Path(__file__).parent
    for item in items:
        if not Path(str(item.fspath)).is_relative_to(here):
            continue
        item.add_marker(pytest.mark.live)
        if not _SETTINGS.live_enabled:
            item.add_marker(
                pytest.mark.skip(reason="set MESA_LIVE=1 to run live OLS tests")
            )
        elif item.get_closest_marker("llm") and not _SETTINGS.llm_enabled:
            item.add_marker(
                pytest.mark.skip(
                    reason="set MESA_LLM_API_KEY (and open scripts/llm_tunnel.sh) "
                    "to run local-LLM tests"
                )
            )


# ---------------------------------------------------------------------------
# Settings + token ledger (session-scoped)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def live_settings() -> LiveSettings:
    return _SETTINGS


@pytest.fixture(scope="session")
def token_ledger(live_settings: LiveSettings) -> TokenLedger:
    return TokenLedger(
        test_budget=live_settings.test_token_budget,
        session_budget=live_settings.session_token_budget,
        max_completion_tokens=live_settings.max_completion_tokens,
    )


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, exitstatus: int, config: pytest.Config
) -> None:
    ledger = getattr(config, "_mesa_token_ledger", None)
    if ledger is None or not ledger.records:
        return
    terminalreporter.section("local-LLM token usage (sparky-2 via LiteLLM)")
    for line in ledger.summary_lines():
        terminalreporter.write_line(line)
    if _SETTINGS.report_path:
        out = Path(_SETTINGS.report_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(ledger.to_json(), indent=2), encoding="utf-8")
        terminalreporter.write_line(f"token report written to {out}")


@pytest.fixture(scope="session", autouse=True)
def _expose_ledger_to_reporter(
    request: pytest.FixtureRequest, token_ledger: TokenLedger
) -> None:
    # pytest_terminal_summary has no fixture access; park the ledger on config.
    request.config._mesa_token_ledger = token_ledger  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Real OLS through the real MCP dispatch path
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ols_reachable(live_settings: LiveSettings) -> None:
    """Skip the whole tier if EMBL-EBI OLS is not answering right now."""
    if not live_settings.live_enabled:
        return
    base = Config().ols.base_url.rstrip("/")
    try:
        resp = httpx.get(f"{base}/ontologies", params={"size": 1}, timeout=15.0)
        resp.raise_for_status()
    except Exception as exc:  # pragma: no cover - network dependent
        pytest.skip(f"OLS unreachable at {base}: {exc}")


@pytest.fixture
def ols_server(ols_reachable: None) -> Iterator[MesaServer]:
    """A ``MesaServer`` whose ``mesa_ols_*`` tools talk to the live OLS API.

    The module-level OLS client singleton is cleared before and after so a
    mock left behind by a unit test can never leak in, and vice versa.
    """
    set_default_client(None)
    token = current_config.set(Config())
    try:
        yield MesaServer(config=Config())
    finally:
        current_config.reset(token)
        set_default_client(None)


# ---------------------------------------------------------------------------
# Local LLM
# ---------------------------------------------------------------------------


@pytest.fixture
async def llm(
    request: pytest.FixtureRequest,
    live_settings: LiveSettings,
    token_ledger: TokenLedger,
) -> AsyncIterator[LLMClient]:
    """An :class:`LLMClient` whose calls are charged to the current test."""
    client = LLMClient(live_settings, token_ledger, test_id=request.node.nodeid)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def agent(ols_server: MesaServer, llm: LLMClient, live_settings: LiveSettings) -> ToolAgent:
    return ToolAgent(
        ols_server,
        llm,
        tool_result_max_chars=live_settings.tool_result_max_chars,
        max_rounds=live_settings.max_tool_rounds,
    )
