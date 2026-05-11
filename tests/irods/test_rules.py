"""Unit tests for ``ds_execute_rule`` / ``ds_list_rules`` / ``ds_get_rule_definition``.

We mock the PRC ``Rule`` class so the tests don't open an iRODS
connection. ``Rule.execute`` is replaced with a stub that returns an
``MsParamArray``-shaped object the helper unpacks.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.errors import ToolError
from mesa_mcp.irods import rules as rule_helpers
from mesa_mcp.irods.tools.execute_rule import (
    ExecuteRuleInput,
    handle_execute_rule,
)
from mesa_mcp.irods.tools.get_rule_definition import (
    GetRuleDefinitionInput,
    handle_get_rule_definition,
)
from mesa_mcp.irods.tools.list_rules import (
    ListRulesInput,
    handle_list_rules,
)


@pytest.fixture
def auth_alice() -> AuthValue:
    return AuthValue(username="alice", zone="iplant", password="pw")


@pytest.fixture
def auth_anon() -> AuthValue:
    return AuthValue(username="anonymous", zone="iplant", auth_scheme="anonymous")


@pytest.fixture
def fake_session() -> MagicMock:
    return MagicMock(name="iRODSSession")


def _make_msparam(label: str, value: str):
    """Construct a tiny stand-in for PRC's ``MsParam`` with ``.label`` + ``.inOutStruct.myStr``."""
    return SimpleNamespace(label=label, inOutStruct=SimpleNamespace(myStr=value))


def _make_msparam_array(params):
    return SimpleNamespace(MsParam_PI=params)


# ---------------------------------------------------------------------------
# Helper-layer tests
# ---------------------------------------------------------------------------


def test_execute_rule_returns_named_outputs(fake_session):
    fake_rule = MagicMock(name="Rule")
    fake_rule.execute.return_value = _make_msparam_array(
        [_make_msparam("outA", "hello"), _make_msparam("outB", "42")]
    )
    with patch("mesa_mcp.irods.rules.Rule", return_value=fake_rule) as cls:
        result = rule_helpers.execute_rule(
            fake_session,
            body="*outA = 'hello'; *outB = '42';",
            output_parameters=["outA", "outB"],
            input_parameters={"x": 1},
        )
    cls.assert_called_once()
    fake_rule.execute.assert_called_once()
    assert result == {"output": {"outA": "hello", "outB": "42"}, "stdout": "", "stderr": ""}


def test_execute_rule_decodes_rule_exec_out(fake_session):
    fake_rule = MagicMock(name="Rule")
    rule_exec = SimpleNamespace(
        stdoutBuf=SimpleNamespace(buf=b"stdout-text\x00"),
        stderrBuf=SimpleNamespace(buf=b"stderr-text"),
    )
    fake_rule.execute.return_value = _make_msparam_array(
        [SimpleNamespace(label="ruleExecOut", inOutStruct=rule_exec)],
    )
    with patch("mesa_mcp.irods.rules.Rule", return_value=fake_rule):
        result = rule_helpers.execute_rule(
            fake_session,
            body="writeLine('stdout', 'stdout-text');",
            output_parameters=["ruleExecOut"],
        )
    assert result["stdout"] == "stdout-text"
    assert result["stderr"] == "stderr-text"


def test_execute_rule_rejects_both_body_and_file(fake_session):
    with pytest.raises(ValueError):
        rule_helpers.execute_rule(fake_session, body="foo", rule_file="bar")


def test_execute_rule_requires_one_of(fake_session):
    with pytest.raises(ValueError):
        rule_helpers.execute_rule(fake_session)


# ---------------------------------------------------------------------------
# Tool-layer tests
# ---------------------------------------------------------------------------


async def test_ds_execute_rule_happy_path(auth_alice, fake_session):
    fake_rule = MagicMock(name="Rule")
    fake_rule.execute.return_value = _make_msparam_array(
        [_make_msparam("greeting", "hi alice")],
    )
    with patch("mesa_mcp.irods.rules.Rule", return_value=fake_rule):
        result = await handle_execute_rule(
            ExecuteRuleInput(
                rule_text="*greeting = 'hi alice'",
                output_parameters=["greeting"],
            ),
            auth_value=auth_alice,
            session=fake_session,
        )
    assert result["output"]["greeting"] == "hi alice"


async def test_ds_execute_rule_invokes_named_rule(auth_alice, fake_session):
    fake_rule = MagicMock(name="Rule")
    fake_rule.execute.return_value = _make_msparam_array([])
    with patch("mesa_mcp.irods.rules.Rule", return_value=fake_rule) as cls:
        await handle_execute_rule(
            ExecuteRuleInput(
                rule_name="msiBuiltinFoo",
                input_parameters={"a": "1", "b": "2"},
                output_parameters=[],
            ),
            auth_value=auth_alice,
            session=fake_session,
        )
    # The wrapper body invokes the named rule with the input params as args.
    body_arg = cls.call_args.kwargs["body"]
    assert "msiBuiltinFoo" in body_arg
    assert "*a" in body_arg
    assert "*b" in body_arg


async def test_ds_execute_rule_xor_rule_name_and_text():
    """Pydantic rejects ``rule_name`` + ``rule_text`` together."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExecuteRuleInput(rule_name="foo", rule_text="bar")
    with pytest.raises(ValidationError):
        ExecuteRuleInput()


async def test_ds_execute_rule_validates_path_inputs(auth_alice, fake_session):
    """Path-typed input parameters get access-checked."""
    fake_rule = MagicMock(name="Rule")
    fake_rule.execute.return_value = _make_msparam_array([])
    # The path is outside the caller's home — assert_allowed rejects it.
    with patch("mesa_mcp.irods.rules.Rule", return_value=fake_rule):
        with pytest.raises(ToolError) as err:
            await handle_execute_rule(
                ExecuteRuleInput(
                    rule_text="msiDoStuff(*p)",
                    input_parameters={"p": "/iplant/home/bob/secret"},
                    output_parameters=[],
                ),
                auth_value=auth_alice,
                session=fake_session,
            )
    assert err.value.code == "forbidden"


async def test_ds_list_rules_returns_envelope(auth_alice, fake_session):
    # ``rule_helpers.list_rules`` returns a stub when the RuleExec model is
    # missing; we let the real helper run against the mock session and just
    # confirm the envelope shape.
    result = await handle_list_rules(
        ListRulesInput(),
        auth_value=auth_alice,
        session=fake_session,
    )
    assert "rules" in result
    assert "note" in result


async def test_ds_list_rules_rejects_anonymous(auth_anon, fake_session):
    with pytest.raises(ToolError) as err:
        await handle_list_rules(
            ListRulesInput(),
            auth_value=auth_anon,
            session=fake_session,
        )
    assert err.value.code == "forbidden"


async def test_ds_get_rule_definition_returns_stub(auth_alice, fake_session):
    result = await handle_get_rule_definition(
        GetRuleDefinitionInput(name="msiSomeRule"),
        auth_value=auth_alice,
        session=fake_session,
    )
    assert result["name"] == "msiSomeRule"
    assert result["definition"] is None
    assert "note" in result
