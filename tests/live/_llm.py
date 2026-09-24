"""Local-LLM harness for the live test tier.

Three pieces, all dependency-free beyond ``httpx`` (already a runtime dep):

* :class:`TokenLedger` — the token manager. Every LLM call is charged to
  the test that made it; per-test and per-session budgets are enforced
  *before* the request goes out (``max_tokens`` is clamped to what is
  left), and a summary table is printed at the end of the session.
* :class:`LLMClient` — a thin OpenAI-compatible client (chat + embeddings)
  pointed at the vLLM models on sparky-2 via the LiteLLM gateway.
* :class:`ToolAgent` — a minimal tool-calling loop that hands the registered
  ``mesa_ols_*`` tools to the model as OpenAI ``functions`` and executes
  each call through :meth:`MesaServer.call`, so the model is hitting the
  *real* OLS API through the *real* MCP dispatch path.

Nothing in here is imported by production code.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from mesa_mcp.errors import ToolError
from mesa_mcp.server import MesaServer, get_tool

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

# Local end of the SSH tunnel opened by ``scripts/llm_tunnel.sh``. The gateway
# itself listens on a docker-bridge address on sparky-2 and is not routable
# from sparky-1, hence the tunnel.
DEFAULT_BASE_URL = "http://127.0.0.1:18000/v1"

# Served model names on the gateway (see litellm.config.yaml on sparky-2).
#   ab-moe     Qwen3.6-35B-A3B  — tool-capable, 131k ctx, ~70 tok/s  (agent)
#   carc-fast  Qwen3-8B         — classify/route, thinking off       (judge)
#   carc-tools Qwen3.8-27B      — slower fallback for the agent role
#   carc-embed Qwen3-Embedding-0.6B                                  (embed)
DEFAULT_AGENT_MODEL = "ab-moe"
DEFAULT_FAST_MODEL = "carc-fast"
DEFAULT_EMBED_MODEL = "carc-embed"


@dataclass(frozen=True)
class LiveSettings:
    """Everything the live tier reads from the environment, in one place."""

    live_enabled: bool
    base_url: str
    api_key: str | None
    agent_model: str
    fast_model: str
    embed_model: str
    # Token management knobs.
    test_token_budget: int
    session_token_budget: int
    max_completion_tokens: int
    tool_result_max_chars: int
    max_tool_rounds: int
    request_timeout: float
    report_path: str | None

    @property
    def llm_enabled(self) -> bool:
        return self.live_enabled and bool(self.api_key)


def _load_dotenv_into_environ(path: Path) -> None:
    """Populate ``os.environ`` from a ``KEY=value`` file without overriding.

    Only the ``MESA_LIVE`` / ``MESA_LLM_*`` keys are read so a stray
    ``.env`` cannot reconfigure the server under test.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not (key == "MESA_LIVE" or key.startswith("MESA_LLM_")):
            continue
        if key in os.environ:
            continue
        os.environ[key] = value.strip().strip("'\"")


def load_settings(repo_root: Path | None = None) -> LiveSettings:
    root = repo_root or Path(__file__).resolve().parents[2]
    _load_dotenv_into_environ(root / ".env")
    env = os.environ

    def _int(name: str, default: int) -> int:
        return int(env.get(name, default))

    return LiveSettings(
        live_enabled=env.get("MESA_LIVE", "").strip().lower() in {"1", "true", "yes"},
        base_url=env.get("MESA_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        api_key=env.get("MESA_LLM_API_KEY") or None,
        agent_model=env.get("MESA_LLM_MODEL", DEFAULT_AGENT_MODEL),
        fast_model=env.get("MESA_LLM_FAST_MODEL", DEFAULT_FAST_MODEL),
        embed_model=env.get("MESA_LLM_EMBED_MODEL", DEFAULT_EMBED_MODEL),
        test_token_budget=_int("MESA_LLM_TEST_TOKEN_BUDGET", 12_000),
        session_token_budget=_int("MESA_LLM_SESSION_TOKEN_BUDGET", 150_000),
        max_completion_tokens=_int("MESA_LLM_MAX_COMPLETION_TOKENS", 1_024),
        tool_result_max_chars=_int("MESA_LLM_TOOL_RESULT_MAX_CHARS", 4_000),
        max_tool_rounds=_int("MESA_LLM_MAX_TOOL_ROUNDS", 6),
        request_timeout=float(env.get("MESA_LLM_REQUEST_TIMEOUT", "300")),
        report_path=env.get("MESA_LLM_TOKEN_REPORT") or None,
    )


# ---------------------------------------------------------------------------
# Token ledger
# ---------------------------------------------------------------------------


class TokenBudgetExceeded(RuntimeError):
    """Raised *before* a request is sent when no token allowance remains."""


@dataclass(frozen=True)
class UsageRecord:
    test: str
    model: str
    kind: str  # "chat" | "embed"
    prompt_tokens: int
    completion_tokens: int
    elapsed_s: float

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class TokenLedger:
    """Charges every model call to a test and enforces the budgets.

    Budgets count *total* tokens (prompt + completion), because on a local
    vLLM box prompt tokens are the real cost driver — prefix caching helps,
    but a 131k-context model fed 40k of tool output per turn will still
    starve the other three backends on the GPU.
    """

    test_budget: int
    session_budget: int
    max_completion_tokens: int
    records: list[UsageRecord] = field(default_factory=list)

    # -- accounting ---------------------------------------------------------

    def charge(self, record: UsageRecord) -> None:
        self.records.append(record)

    def spent_by_test(self, test: str) -> int:
        return sum(r.total_tokens for r in self.records if r.test == test)

    @property
    def spent_session(self) -> int:
        return sum(r.total_tokens for r in self.records)

    def remaining_for(self, test: str) -> int:
        return min(
            self.test_budget - self.spent_by_test(test),
            self.session_budget - self.spent_session,
        )

    def allowance(self, test: str, requested: int | None = None) -> int:
        """Tokens the next completion may generate for ``test``.

        The allowance is the smaller of the caller's request (or the default
        completion cap) and what is left in the tighter of the two budgets.
        A non-positive result means the call must not be made.
        """
        cap = self.max_completion_tokens if requested is None else requested
        remaining = self.remaining_for(test)
        if remaining <= 0:
            raise TokenBudgetExceeded(
                f"{test}: token budget exhausted "
                f"(test {self.spent_by_test(test)}/{self.test_budget}, "
                f"session {self.spent_session}/{self.session_budget})"
            )
        return max(1, min(cap, remaining))

    # -- reporting ------------------------------------------------------------

    def by_model(self) -> dict[str, tuple[int, int, int]]:
        out: dict[str, list[int]] = {}
        for r in self.records:
            row = out.setdefault(r.model, [0, 0, 0])
            row[0] += r.prompt_tokens
            row[1] += r.completion_tokens
            row[2] += 1
        return {k: (v[0], v[1], v[2]) for k, v in out.items()}

    def by_test(self) -> dict[str, tuple[int, int, int, float]]:
        out: dict[str, list[float]] = {}
        for r in self.records:
            row = out.setdefault(r.test, [0, 0, 0, 0.0])
            row[0] += r.prompt_tokens
            row[1] += r.completion_tokens
            row[2] += 1
            row[3] += r.elapsed_s
        return {k: (int(v[0]), int(v[1]), int(v[2]), v[3]) for k, v in out.items()}

    def summary_lines(self) -> list[str]:
        if not self.records:
            return ["no LLM calls were made"]
        lines = [
            f"{'test':<70} {'prompt':>8} {'compl':>7} {'calls':>5} {'secs':>7}",
        ]
        for test, (p, c, n, s) in sorted(self.by_test().items()):
            short = test if len(test) <= 70 else "…" + test[-69:]
            lines.append(f"{short:<70} {p:>8} {c:>7} {n:>5} {s:>7.1f}")
        lines.append("")
        lines.append(f"{'model':<70} {'prompt':>8} {'compl':>7} {'calls':>5}")
        for model, (p, c, n) in sorted(self.by_model().items()):
            lines.append(f"{model:<70} {p:>8} {c:>7} {n:>5}")
        lines.append("")
        lines.append(
            f"session total {self.spent_session} / {self.session_budget} tokens "
            f"(per-test budget {self.test_budget}, completion cap "
            f"{self.max_completion_tokens})"
        )
        return lines

    def to_json(self) -> dict[str, Any]:
        return {
            "budgets": {
                "test": self.test_budget,
                "session": self.session_budget,
                "max_completion_tokens": self.max_completion_tokens,
            },
            "session_total": self.spent_session,
            "by_model": {
                m: {"prompt": p, "completion": c, "calls": n}
                for m, (p, c, n) in self.by_model().items()
            },
            "by_test": {
                t: {"prompt": p, "completion": c, "calls": n, "seconds": round(s, 2)}
                for t, (p, c, n, s) in self.by_test().items()
            },
            "records": [
                {
                    "test": r.test,
                    "model": r.model,
                    "kind": r.kind,
                    "prompt": r.prompt_tokens,
                    "completion": r.completion_tokens,
                    "seconds": round(r.elapsed_s, 3),
                }
                for r in self.records
            ],
        }


# ---------------------------------------------------------------------------
# OpenAI-compatible client
# ---------------------------------------------------------------------------


@dataclass
class ChatResult:
    message: dict[str, Any]
    usage: UsageRecord
    finish_reason: str | None
    raw: dict[str, Any]

    @property
    def content(self) -> str:
        return self.message.get("content") or ""

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        return list(self.message.get("tool_calls") or [])


class LLMClient:
    """Chat + embeddings against the gateway, every call charged to a test."""

    def __init__(
        self,
        settings: LiveSettings,
        ledger: TokenLedger,
        *,
        test_id: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        if not settings.api_key:
            raise RuntimeError("LLMClient needs MESA_LLM_API_KEY")
        self.settings = settings
        self.ledger = ledger
        self.test_id = test_id
        self._own_http = http is None
        self.http = http or httpx.AsyncClient(
            base_url=settings.base_url,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=httpx.Timeout(settings.request_timeout, connect=10.0),
        )

    async def aclose(self) -> None:
        if self._own_http:
            await self.http.aclose()

    # -- endpoints ------------------------------------------------------------

    async def models(self) -> list[str]:
        resp = await self.http.get("/models")
        resp.raise_for_status()
        return [m["id"] for m in resp.json().get("data", [])]

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        think: bool = False,
    ) -> ChatResult:
        """One chat completion, with ``max_tokens`` clamped to the budget.

        ``think=False`` sends ``enable_thinking: false`` so Qwen3-family
        models skip chain-of-thought. It is honoured by carc-fast; ab-moe
        has no working off switch (its reasoning is stripped into
        ``reasoning_content`` by the server-side parser but still billed as
        completion tokens), which is exactly why the budget clamps here.
        """
        model = model or self.settings.agent_model
        allowance = self.ledger.allowance(self.test_id, max_tokens)
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": allowance,
            "temperature": temperature,
            "chat_template_kwargs": {"enable_thinking": think},
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"

        started = time.monotonic()
        resp = await self.http.post("/chat/completions", json=body)
        elapsed = time.monotonic() - started
        if resp.status_code >= 400:
            raise RuntimeError(
                f"{model}: HTTP {resp.status_code} from {self.settings.base_url}: "
                f"{resp.text[:500]}"
            )
        data = resp.json()
        usage = data.get("usage") or {}
        record = UsageRecord(
            test=self.test_id,
            model=model,
            kind="chat",
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            elapsed_s=elapsed,
        )
        self.ledger.charge(record)
        choice = (data.get("choices") or [{}])[0]
        return ChatResult(
            message=choice.get("message") or {},
            usage=record,
            finish_reason=choice.get("finish_reason"),
            raw=data,
        )

    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        model = model or self.settings.embed_model
        # Embeddings generate nothing, but their prompt tokens still count.
        self.ledger.allowance(self.test_id, 1)
        started = time.monotonic()
        resp = await self.http.post("/embeddings", json={"model": model, "input": texts})
        elapsed = time.monotonic() - started
        if resp.status_code >= 400:
            raise RuntimeError(
                f"{model}: HTTP {resp.status_code} from {self.settings.base_url}: "
                f"{resp.text[:500]}"
            )
        data = resp.json()
        usage = data.get("usage") or {}
        self.ledger.charge(
            UsageRecord(
                test=self.test_id,
                model=model,
                kind="embed",
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=0,
                elapsed_s=elapsed,
            )
        )
        rows = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
        return [row["embedding"] for row in rows]


# ---------------------------------------------------------------------------
# Tool-calling agent over the mesa-mcp registry
# ---------------------------------------------------------------------------


def openai_tool_spec(tool_name: str) -> dict[str, Any]:
    """Translate a registered mesa-mcp tool into an OpenAI ``tools`` entry."""
    spec = get_tool(tool_name)
    if spec.input_model is None:
        params: dict[str, Any] = {"type": "object", "properties": {}}
    else:
        params = spec.input_model.model_json_schema()
        params.pop("title", None)
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": params,
        },
    }


@dataclass
class ToolCallTrace:
    name: str
    args: dict[str, Any]
    result: dict[str, Any]
    error: str | None = None


@dataclass
class AgentRun:
    final_text: str
    calls: list[ToolCallTrace]
    rounds: int
    finish_reason: str | None

    def calls_to(self, name: str) -> list[ToolCallTrace]:
        return [c for c in self.calls if c.name == name]

    def results_for(self, name: str) -> list[dict[str, Any]]:
        return [c.result for c in self.calls_to(name)]


SYSTEM_PROMPT = (
    "You are a metadata assistant for a research data store. You answer by "
    "calling the provided ontology tools (EMBL-EBI OLS over the OBO Foundry "
    "ontologies) and reporting exactly what they return — never invent an "
    "IRI, CURIE, or label. Keep tool result sizes small: prefer small `size` "
    "arguments and restrict searches to one ontology when the user names it. "
    "When you have the answer, reply in one short line with no preamble."
)


class ToolAgent:
    """Minimal agent loop: model → tool calls → MesaServer.call → model …"""

    def __init__(
        self,
        server: MesaServer,
        llm: LLMClient,
        *,
        tool_result_max_chars: int,
        max_rounds: int,
    ) -> None:
        self.server = server
        self.llm = llm
        self.tool_result_max_chars = tool_result_max_chars
        self.max_rounds = max_rounds

    def _pack_result(self, result: dict[str, Any]) -> str:
        """Serialise a tool result, truncated so prompt tokens stay bounded."""
        text = json.dumps(result, separators=(",", ":"), ensure_ascii=False)
        if len(text) <= self.tool_result_max_chars:
            return text
        return text[: self.tool_result_max_chars] + '…","truncated":true}'

    async def _execute(self, call: dict[str, Any]) -> ToolCallTrace:
        fn = call.get("function") or {}
        name = fn.get("name", "")
        raw_args = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except json.JSONDecodeError as exc:
            return ToolCallTrace(name, {}, {"error": f"bad JSON arguments: {exc}"}, str(exc))
        try:
            result = await self.server.call(name, args)
            return ToolCallTrace(name, args, result)
        except ToolError as exc:
            payload = {"error": exc.code, "message": exc.message}
            return ToolCallTrace(name, args, payload, exc.code)

    async def run(
        self,
        task: str,
        *,
        tools: list[str],
        system: str = SYSTEM_PROMPT,
        model: str | None = None,
    ) -> AgentRun:
        tool_specs = [openai_tool_spec(n) for n in tools]
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]
        calls: list[ToolCallTrace] = []
        finish: str | None = None
        for round_no in range(1, self.max_rounds + 1):
            result = await self.llm.chat(messages, tools=tool_specs, model=model)
            finish = result.finish_reason
            tool_calls = result.tool_calls
            if not tool_calls:
                return AgentRun(result.content.strip(), calls, round_no, finish)
            # Echo the assistant turn (without server-side reasoning text).
            messages.append(
                {
                    "role": "assistant",
                    "content": result.content or None,
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                trace = await self._execute(call)
                calls.append(trace)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "name": trace.name,
                        "content": self._pack_result(trace.result),
                    }
                )
        # Out of rounds: ask for a final answer without tools so the test can
        # still assert on something meaningful (and the trace is intact).
        messages.append(
            {
                "role": "user",
                "content": "Stop calling tools. Give your final answer now in one line.",
            }
        )
        result = await self.llm.chat(messages, model=model)
        return AgentRun(result.content.strip(), calls, self.max_rounds + 1, result.finish_reason)
