"""Unit tests for the policy tools (``ds_list_policies``, ``ds_get_policy_config``,
``mesa_policy_enable``, ``mesa_policy_disable``).

PCF tools return documented stubs; we test the envelope shape. The
mesa-specific policy toggles read and write AVUs through a mocked
``iRODSSession`` and we assert on the correct ``metadata.add`` /
``metadata.remove`` calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.errors import ToolError
from mesa_mcp.irods.tools.get_policy_config import (
    GetPolicyConfigInput,
    handle_get_policy_config,
)
from mesa_mcp.irods.tools.list_policies import (
    ListPoliciesInput,
    handle_list_policies,
)
from mesa_mcp.ols.tools.policy_enable import (
    PolicyToggleInput,
    handle_policy_disable,
    handle_policy_enable,
)


@pytest.fixture
def auth_alice() -> AuthValue:
    return AuthValue(username="alice", zone="iplant", password="pw")


@pytest.fixture
def fake_session() -> MagicMock:
    session = MagicMock(name="iRODSSession")
    # Default: metadata.get returns an empty list (no existing AVUs).
    session.metadata.get.return_value = []
    return session


async def test_ds_list_policies_returns_stub(auth_alice, fake_session):
    result = await handle_list_policies(
        ListPoliciesInput(),
        auth_value=auth_alice,
        session=fake_session,
    )
    assert result["policies"] == []
    assert "Policy Composition" in result["note"]


async def test_ds_get_policy_config_returns_stub(auth_alice, fake_session):
    result = await handle_get_policy_config(
        GetPolicyConfigInput(name="replicate"),
        auth_value=auth_alice,
        session=fake_session,
    )
    assert result["name"] == "replicate"
    assert result["config"] is None


async def test_mesa_policy_enable_writes_the_right_avu(auth_alice, fake_session):
    """Enabling writes ``mesa.policy.<name>=true`` on the project collection."""
    # ``session.collections.get`` is the "is collection" probe — let it succeed.
    fake_session.collections.get.return_value = MagicMock()
    fake_session.metadata.get.return_value = []

    result = await handle_policy_enable(
        PolicyToggleInput(
            project_path="/iplant/home/alice/proj",
            policy_name="auto_ducklake",
        ),
        auth_value=auth_alice,
        session=fake_session,
    )

    assert result["enabled"] is True
    assert result["policy"] == "auto_ducklake"
    # The AVU add should target the project collection.
    fake_session.metadata.add.assert_called_once()
    call = fake_session.metadata.add.call_args
    # The third positional argument is an iRODSMeta-shaped object.
    meta = call.args[2]
    assert getattr(meta, "name", None) == "mesa.policy.auto_ducklake"
    assert getattr(meta, "value", None) == "true"


async def test_mesa_policy_enable_replaces_existing_avu(auth_alice, fake_session):
    """Existing matching AVUs are removed before re-adding (idempotent toggle)."""
    fake_session.collections.get.return_value = MagicMock()
    existing = SimpleNamespace(name="mesa.policy.auto_ducklake", value="true", units="")
    fake_session.metadata.get.return_value = [existing]

    await handle_policy_enable(
        PolicyToggleInput(
            project_path="/iplant/home/alice/proj",
            policy_name="auto_ducklake",
        ),
        auth_value=auth_alice,
        session=fake_session,
    )

    # The existing AVU is removed, then a fresh one is added.
    fake_session.metadata.remove.assert_called_once()
    fake_session.metadata.add.assert_called_once()


async def test_mesa_policy_disable_removes_avu_without_re_adding(auth_alice, fake_session):
    fake_session.collections.get.return_value = MagicMock()
    existing = SimpleNamespace(name="mesa.policy.auto_ducklake", value="true", units="")
    fake_session.metadata.get.return_value = [existing]

    result = await handle_policy_disable(
        PolicyToggleInput(
            project_path="/iplant/home/alice/proj",
            policy_name="auto_ducklake",
        ),
        auth_value=auth_alice,
        session=fake_session,
    )

    assert result["enabled"] is False
    fake_session.metadata.remove.assert_called_once()
    fake_session.metadata.add.assert_not_called()


async def test_mesa_policy_enable_rejects_data_object(auth_alice, fake_session):
    """If the path is not a collection, the tool fails up-front."""
    fake_session.collections.get.side_effect = RuntimeError("not a collection")

    with pytest.raises(ToolError) as err:
        await handle_policy_enable(
            PolicyToggleInput(
                project_path="/iplant/home/alice/proj/file.csv",
                policy_name="auto_ducklake",
            ),
            auth_value=auth_alice,
            session=fake_session,
        )
    assert err.value.code == "invalid_argument"


async def test_mesa_policy_enable_records_into_ducklake(auth_alice, fake_session):
    """``handle_policy_enable`` calls ``record_avu_change`` with the right kwargs."""
    fake_session.collections.get.return_value = MagicMock()
    fake_session.metadata.get.return_value = []

    captured: dict[str, object] = {}

    async def fake_record(**kwargs):
        captured.update(kwargs)

    with patch(
        "mesa_mcp.ols.tools.policy_enable.record_avu_change",
        side_effect=fake_record,
    ) as rec:
        await handle_policy_enable(
            PolicyToggleInput(
                project_path="/iplant/home/alice/proj",
                policy_name="auto_ducklake",
            ),
            auth_value=auth_alice,
            session=fake_session,
        )

    rec.assert_called_once()
    assert captured["attribute"] == "mesa.policy.auto_ducklake"
    assert captured["value"] == "true"
    assert captured["op"] == "add"
    assert captured["target_type"] == "collection"
    assert captured["tool_name"] == "mesa_policy_enable"
