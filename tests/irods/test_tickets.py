"""Unit tests for the ticket lifecycle tools.

We exercise full create → modify → delete + ``ds_use_ticket`` flows
against a :class:`MagicMock` ``iRODSSession`` so the tests stay
hermetic. The ``Ticket`` and ``TicketQuery`` classes from
``python-irodsclient`` are imported in the helper module under test; we
patch them at the use-site so the helpers don't try to send real iRODS
messages.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import current_ticket
from mesa_mcp.errors import ToolError
from mesa_mcp.irods import tickets as ticket_helpers
from mesa_mcp.irods.tools.create_ticket import (
    CreateTicketInput,
    handle_create_ticket,
)
from mesa_mcp.irods.tools.delete_ticket import (
    DeleteTicketInput,
    handle_delete_ticket,
)
from mesa_mcp.irods.tools.get_ticket_info import (
    GetTicketInfoInput,
    handle_get_ticket_info,
)
from mesa_mcp.irods.tools.list_tickets import (
    ListTicketsInput,
    handle_list_tickets,
)
from mesa_mcp.irods.tools.modify_ticket import (
    ModifyTicketInput,
    handle_modify_ticket,
)
from mesa_mcp.irods.tools.use_ticket import (
    UseTicketInput,
    handle_use_ticket,
)


@pytest.fixture
def auth_alice() -> AuthValue:
    """A non-anonymous auth value bound to ``/iplant/home/alice``."""
    return AuthValue(username="alice", zone="iplant", password="pw")


@pytest.fixture
def auth_anon() -> AuthValue:
    """Anonymous caller; every ticket tool refuses these."""
    return AuthValue(username="anonymous", zone="iplant", auth_scheme="anonymous")


@pytest.fixture
def fake_session() -> MagicMock:
    return MagicMock(name="iRODSSession")


# ---------------------------------------------------------------------------
# Helper-layer tests (tickets.py)
# ---------------------------------------------------------------------------


def test_issue_ticket_applies_all_restrictions(fake_session):
    """Every supplied restriction translates into a Ticket.modify call."""
    fake_ticket = MagicMock(name="Ticket")
    fake_ticket.string = "T1234567"
    with patch("mesa_mcp.irods.tickets.Ticket", return_value=fake_ticket) as ticket_cls:
        record = ticket_helpers.issue_ticket(
            fake_session,
            "/iplant/home/alice/data",
            "write",
            uses_allowed=5,
            expiry="2026-12-31T23:59:59Z",
            write_byte_limit=1024,
            host_restriction="10.0.0.1",
            user_restriction="bob",
        )

    ticket_cls.assert_called_once_with(fake_session)
    fake_ticket.issue.assert_called_once_with("write", "/iplant/home/alice/data")
    # All five modify calls — uses, expire, write-bytes, add host, add user.
    assert fake_ticket.modify.call_count == 5
    assert record["ticket"] == "T1234567"
    assert record["mode"] == "write"
    assert record["uses_allowed"] == 5
    assert record["expiry"] == "2026-12-31T23:59:59Z"


def test_issue_ticket_rejects_bad_mode(fake_session):
    with pytest.raises(ValueError, match="ticket mode"):
        ticket_helpers.issue_ticket(fake_session, "/iplant/home/alice/data", "execute")  # type: ignore[arg-type]


def test_issue_ticket_rejects_write_bytes_on_read(fake_session):
    with patch("mesa_mcp.irods.tickets.Ticket"):
        with pytest.raises(ValueError, match="write_byte_limit"):
            ticket_helpers.issue_ticket(
                fake_session,
                "/iplant/home/alice/data",
                "read",
                write_byte_limit=42,
            )


def test_modify_ticket_applies_restrictions(fake_session):
    fake_ticket = MagicMock(name="Ticket")
    with patch("mesa_mcp.irods.tickets.Ticket", return_value=fake_ticket):
        out = ticket_helpers.modify_ticket(
            fake_session,
            "T1",
            uses=3,
            expiry="2027-01-01T00:00:00Z",
        )
    assert out == {"ticket": "T1", "uses": 3, "expiry": "2027-01-01T00:00:00Z"}
    assert fake_ticket.modify.call_count == 2


def test_revoke_ticket(fake_session):
    fake_ticket = MagicMock(name="Ticket")
    with patch("mesa_mcp.irods.tickets.Ticket", return_value=fake_ticket):
        out = ticket_helpers.revoke_ticket(fake_session, "T1")
    fake_ticket.delete.assert_called_once()
    assert out == {"ticket": "T1", "deleted": True}


# ---------------------------------------------------------------------------
# Tool-layer tests
# ---------------------------------------------------------------------------


async def test_ds_list_tickets_rejects_anonymous(auth_anon, fake_session):
    with pytest.raises(ToolError) as err:
        await handle_list_tickets(
            ListTicketsInput(),
            auth_value=auth_anon,
            session=fake_session,
        )
    assert err.value.code == "forbidden"


async def test_ds_list_tickets_happy_path(auth_alice, fake_session):
    with patch.object(ticket_helpers, "list_tickets", return_value=[{"ticket": {"id": 1}}]):
        result = await handle_list_tickets(
            ListTicketsInput(),
            auth_value=auth_alice,
            session=fake_session,
        )
    assert result == {"tickets": [{"ticket": {"id": 1}}]}


async def test_ds_get_ticket_info_not_found(auth_alice, fake_session):
    with patch.object(ticket_helpers, "lookup_ticket", return_value=None):
        with pytest.raises(ToolError) as err:
            await handle_get_ticket_info(
                GetTicketInfoInput(name="missing"),
                auth_value=auth_alice,
                session=fake_session,
            )
    assert err.value.code == "not_found"


async def test_ds_get_ticket_info_returns_payload(auth_alice, fake_session):
    payload = {"ticket": {"id": 7, "string": "T7"}, "restrictions": {}}
    with patch.object(ticket_helpers, "lookup_ticket", return_value=payload):
        result = await handle_get_ticket_info(
            GetTicketInfoInput(name="T7"),
            auth_value=auth_alice,
            session=fake_session,
        )
    assert result == payload


async def test_ds_create_ticket_happy_path(auth_alice, fake_session):
    with patch.object(
        ticket_helpers,
        "issue_ticket",
        return_value={"ticket": "Tnew", "mode": "read", "path": "/iplant/home/alice/data"},
    ) as issue:
        result = await handle_create_ticket(
            CreateTicketInput(
                path="/iplant/home/alice/data",
                mode="read",
                uses_allowed=3,
            ),
            auth_value=auth_alice,
            session=fake_session,
        )
    assert result["ticket"] == "Tnew"
    # ``issue_ticket`` is called with the *normalised* path.
    args, kwargs = issue.call_args
    assert args[1] == "/iplant/home/alice/data"
    assert args[2] == "read"
    assert kwargs["uses_allowed"] == 3


async def test_ds_create_ticket_rejects_write_bytes_on_read(auth_alice, fake_session):
    with pytest.raises(ToolError) as err:
        await handle_create_ticket(
            CreateTicketInput(
                path="/iplant/home/alice/data",
                mode="read",
                write_byte_limit=42,
            ),
            auth_value=auth_alice,
            session=fake_session,
        )
    assert err.value.code == "invalid_argument"


async def test_ds_create_ticket_rejects_path_outside_home(auth_alice, fake_session):
    with pytest.raises(ToolError) as err:
        await handle_create_ticket(
            CreateTicketInput(path="/iplant/home/bob/private", mode="read"),
            auth_value=auth_alice,
            session=fake_session,
        )
    assert err.value.code == "forbidden"


async def test_ds_modify_ticket_input_rejects_mode_field():
    """The Pydantic model does not allow a 'mode' input — mode is immutable."""
    # Pydantic accepts unknown fields by default (no ``extra='forbid'``), so
    # we instead confirm the model does not advertise a ``mode`` field.
    assert "mode" not in ModifyTicketInput.model_fields


async def test_ds_modify_ticket_happy_path(auth_alice, fake_session):
    return_value = {"ticket": "T1", "uses": 9}
    with patch.object(ticket_helpers, "modify_ticket", return_value=return_value) as mod:
        result = await handle_modify_ticket(
            ModifyTicketInput(ticket="T1", uses=9),
            auth_value=auth_alice,
            session=fake_session,
        )
    assert result == {"ticket": "T1", "uses": 9}
    mod.assert_called_once()


async def test_ds_delete_ticket_happy_path(auth_alice, fake_session):
    return_value = {"ticket": "T1", "deleted": True}
    with patch.object(ticket_helpers, "revoke_ticket", return_value=return_value):
        result = await handle_delete_ticket(
            DeleteTicketInput(ticket="T1"),
            auth_value=auth_alice,
            session=fake_session,
        )
    assert result == {"ticket": "T1", "deleted": True}


async def test_ds_use_ticket_sets_contextvar(auth_alice, fake_session):
    """``ds_use_ticket`` populates current_ticket so downstream writes see it."""
    fake_ticket = MagicMock(name="Ticket")
    token = current_ticket.set(None)  # baseline
    try:
        with patch("mesa_mcp.irods.tools.use_ticket.Ticket", return_value=fake_ticket):
            result = await handle_use_ticket(
                UseTicketInput(ticket="TUseTest"),
                auth_value=auth_alice,
                session=fake_session,
            )
        # ``supply`` was invoked once as a validity probe.
        fake_ticket.supply.assert_called_once()
        assert result["ticket"] == "TUseTest"
        assert result["bound"] is True
        assert current_ticket.get() == "TUseTest"
    finally:
        current_ticket.reset(token)


async def test_ds_use_ticket_propagates_irods_failure(auth_alice, fake_session):
    fake_ticket = MagicMock(name="Ticket")
    fake_ticket.supply.side_effect = RuntimeError("bad ticket")
    with patch("mesa_mcp.irods.tools.use_ticket.Ticket", return_value=fake_ticket):
        with pytest.raises(ToolError) as err:
            await handle_use_ticket(
                UseTicketInput(ticket="bogus"),
                auth_value=auth_alice,
                session=fake_session,
            )
    assert err.value.code == "irods_error"


async def test_ds_use_ticket_rejects_anonymous(auth_anon, fake_session):
    with pytest.raises(ToolError) as err:
        await handle_use_ticket(
            UseTicketInput(ticket="T1"),
            auth_value=auth_anon,
            session=fake_session,
        )
    assert err.value.code == "forbidden"
