"""Ticket-restriction errors must be actionable, not bare numbers.

python-irodsclient 3.3.0 maps only three iRODS ticket error codes to
exception classes. The rest arrive as ``KeyError(<code>)`` from
``get_exception_by_code``. Passed through a generic handler, the caller
receives a message consisting of the string ``-893000`` and no way to
tell a restricted ticket from a client bug.

Verified against a live CyVerse zone: restricting a ticket to another
user and then reading a data object through it raises
``KeyError(-893000)`` — CAT_TICKET_USER_EXCLUDED.
"""

from __future__ import annotations

import pytest

from mesa_mcp.errors import ToolError
from mesa_mcp.irods import ticket_errors


class _MappedException(Exception):
    """Stands in for a PRC exception class that does expose ``.code``."""

    code = -892000


def test_unmapped_keyerror_is_recognised():
    """The shape actually observed against CyVerse."""
    assert ticket_errors.irods_error_code(KeyError(-893000)) == -893000


def test_mapped_exception_code_is_recognised():
    assert ticket_errors.irods_error_code(_MappedException()) == -892000


def test_unrelated_keyerror_is_not_a_ticket_error():
    """A genuine dict miss must not be dressed up as a ticket refusal."""
    assert ticket_errors.irods_error_code(KeyError("some_key")) is None
    assert ticket_errors.as_tool_error(KeyError("some_key"), context="x") is None


def test_unknown_code_falls_through():
    """Codes outside the ticket range are left to existing handling."""
    assert ticket_errors.as_tool_error(KeyError(-12345), context="x") is None


def test_user_excluded_produces_an_actionable_error():
    err = ticket_errors.as_tool_error(KeyError(-893000), context="Failed to read")
    assert isinstance(err, ToolError)
    assert err.code == "forbidden"
    # The message must explain the cause, not restate the number.
    assert "restricted to specific users" in err.message
    assert "-893000" not in err.message
    assert err.details["irods_error"] == "CAT_TICKET_USER_EXCLUDED"
    assert err.details["irods_code"] == -893000


@pytest.mark.parametrize(
    ("code", "name"),
    [
        (-890000, "CAT_TICKET_INVALID"),
        (-891000, "CAT_TICKET_EXPIRED"),
        (-892000, "CAT_TICKET_USES_EXCEEDED"),
        (-893000, "CAT_TICKET_USER_EXCLUDED"),
        (-894000, "CAT_TICKET_HOST_EXCLUDED"),
        (-895000, "CAT_TICKET_GROUP_EXCLUDED"),
        (-896000, "CAT_TICKET_WRITE_USES_EXCEEDED"),
        (-897000, "CAT_TICKET_WRITE_BYTES_EXCEEDED"),
    ],
)
def test_every_ticket_code_is_named(code, name):
    err = ticket_errors.as_tool_error(KeyError(code), context="ctx")
    assert err is not None
    assert err.details["irods_error"] == name
    assert err.code == "forbidden"


def test_ticket_string_is_never_placed_in_details():
    """A ticket is a bearer capability; error payloads get logged."""
    err = ticket_errors.as_tool_error(
        KeyError(-893000), context="ctx", details={"path": "/z/home/u/c"}
    )
    assert err is not None
    assert "ticket" not in err.details
    assert err.details["path"] == "/z/home/u/c"
