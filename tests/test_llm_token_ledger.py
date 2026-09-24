"""Hermetic tests for the live tier's token manager (``tests/live/_llm.py``).

These run in the normal suite: no network, no models. They pin the budget
arithmetic the live tests rely on so a refactor there cannot silently
turn the clamp off.
"""

from __future__ import annotations

import pytest

from tests.live._llm import TokenBudgetExceeded, TokenLedger, UsageRecord, openai_tool_spec


def _rec(test: str, prompt: int, completion: int, model: str = "m") -> UsageRecord:
    return UsageRecord(
        test=test, model=model, kind="chat", prompt_tokens=prompt,
        completion_tokens=completion, elapsed_s=0.1,
    )


@pytest.fixture
def ledger() -> TokenLedger:
    return TokenLedger(test_budget=100, session_budget=250, max_completion_tokens=40)


class TestAllowance:
    def test_default_is_completion_cap(self, ledger: TokenLedger) -> None:
        assert ledger.allowance("t1") == 40

    def test_explicit_request_below_cap_is_honoured(self, ledger: TokenLedger) -> None:
        assert ledger.allowance("t1", 8) == 8

    def test_clamped_by_test_budget(self, ledger: TokenLedger) -> None:
        ledger.charge(_rec("t1", prompt=60, completion=30))  # 90 of 100 spent
        assert ledger.allowance("t1", 1000) == 10

    def test_clamped_by_session_budget_across_tests(self, ledger: TokenLedger) -> None:
        ledger.charge(_rec("t1", 100, 0))
        ledger.charge(_rec("t2", 100, 0))
        ledger.charge(_rec("t3", 40, 0))  # session 240 of 250
        assert ledger.allowance("t4") == 10

    def test_exhausted_test_budget_refuses_before_call(self, ledger: TokenLedger) -> None:
        ledger.charge(_rec("t1", 70, 30))
        with pytest.raises(TokenBudgetExceeded, match="t1"):
            ledger.allowance("t1")

    def test_exhausted_session_budget_refuses_other_tests(self, ledger: TokenLedger) -> None:
        for name in ("a", "b", "c"):
            ledger.charge(_rec(name, 90, 0))
        with pytest.raises(TokenBudgetExceeded, match="session 270/250"):
            ledger.allowance("fresh")

    def test_allowance_never_below_one(self, ledger: TokenLedger) -> None:
        assert ledger.allowance("t1", 0) == 1


class TestReporting:
    def test_totals_by_model_and_test(self, ledger: TokenLedger) -> None:
        ledger.charge(_rec("t1", 10, 5, model="ab-moe"))
        ledger.charge(_rec("t1", 20, 5, model="carc-fast"))
        ledger.charge(_rec("t2", 1, 1, model="ab-moe"))
        assert ledger.by_model() == {"ab-moe": (11, 6, 2), "carc-fast": (20, 5, 1)}
        by_test = ledger.by_test()
        assert by_test["t1"][:3] == (30, 10, 2)
        assert ledger.spent_session == 42

    def test_summary_mentions_budgets(self, ledger: TokenLedger) -> None:
        ledger.charge(_rec("t1", 10, 5))
        text = "\n".join(ledger.summary_lines())
        assert "session total 15 / 250" in text
        assert "per-test budget 100" in text

    def test_json_report_shape(self, ledger: TokenLedger) -> None:
        ledger.charge(_rec("t1", 10, 5))
        report = ledger.to_json()
        assert report["budgets"] == {"test": 100, "session": 250, "max_completion_tokens": 40}
        assert report["records"][0]["prompt"] == 10
        assert report["by_test"]["t1"]["calls"] == 1


class TestToolSpecTranslation:
    def test_registered_tool_becomes_openai_function(self) -> None:
        import mesa_mcp.ols  # noqa: F401  (registration side effect)

        spec = openai_tool_spec("mesa_ols_search_terms")
        assert spec["type"] == "function"
        fn = spec["function"]
        assert fn["name"] == "mesa_ols_search_terms"
        assert fn["description"]
        assert "query" in fn["parameters"]["properties"]
        assert "query" in fn["parameters"]["required"]
        assert "title" not in fn["parameters"]
