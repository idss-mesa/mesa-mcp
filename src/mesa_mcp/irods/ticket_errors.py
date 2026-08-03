"""Translate iRODS ticket errors into meaningful :class:`ToolError`\\ s.

``python-irodsclient`` 3.3.0 maps only three of the iRODS ticket error
codes to exception classes (``CAT_TICKET_INVALID`` -890000,
``CAT_TICKET_EXPIRED`` -891000, ``CAT_TICKET_USES_EXCEEDED`` -892000).
Every other code in the range reaches the caller as a bare
``KeyError(<code>)`` raised by ``irods.exception.get_exception_by_code``
— which is indistinguishable from a client bug and, passed through a
generic handler, produces a tool response whose entire message is the
string ``-893000``.

That is not hypothetical. Restricting a ticket to another user and then
reading a data object through it raises ``KeyError(-893000)``: the zone
correctly refusing the read (``CAT_TICKET_USER_EXCLUDED``), reported as
if the server had never been reached.

This module names the whole range so a restricted ticket produces an
actionable message. Codes are from ``rodsErrorTable.h``.
"""

from __future__ import annotations

from typing import Any

from mesa_mcp.errors import ToolError

#: iRODS ticket error codes and the caller-facing explanation for each.
#: ``code`` is the mesa-mcp ToolError code; ``hint`` is written for the
#: person holding the ticket, not for a zone administrator.
TICKET_ERRORS: dict[int, tuple[str, str, str]] = {
    -890000: (
        "CAT_TICKET_INVALID",
        "forbidden",
        "The ticket is not valid. It may have been revoked, or the string "
        "may be mistyped.",
    ),
    -891000: (
        "CAT_TICKET_EXPIRED",
        "forbidden",
        "The ticket has passed its expiry time.",
    ),
    -892000: (
        "CAT_TICKET_USES_EXCEEDED",
        "forbidden",
        "The ticket has been used its maximum number of times.",
    ),
    -893000: (
        "CAT_TICKET_USER_EXCLUDED",
        "forbidden",
        "The ticket is restricted to specific users and the current user is "
        "not among them.",
    ),
    -894000: (
        "CAT_TICKET_HOST_EXCLUDED",
        "forbidden",
        "The ticket is restricted to specific hosts and this host is not "
        "among them.",
    ),
    -895000: (
        "CAT_TICKET_GROUP_EXCLUDED",
        "forbidden",
        "The ticket is restricted to specific groups and the current user is "
        "not a member of any of them.",
    ),
    -896000: (
        "CAT_TICKET_WRITE_USES_EXCEEDED",
        "forbidden",
        "The ticket has reached its limit on the number of writes.",
    ),
    -897000: (
        "CAT_TICKET_WRITE_BYTES_EXCEEDED",
        "forbidden",
        "The ticket has reached its limit on bytes written.",
    ),
}


def irods_error_code(exc: BaseException) -> int | None:
    """Recover an iRODS error code from an exception, if it carries one.

    Handles both shapes: a mapped ``iRODSException`` subclass exposing
    ``.code``, and the bare ``KeyError(<code>)`` that
    ``get_exception_by_code`` raises for codes it does not know.
    """
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    if isinstance(exc, KeyError) and exc.args:
        candidate = exc.args[0]
        if isinstance(candidate, int):
            return candidate
    return None


def as_tool_error(
    exc: BaseException,
    *,
    context: str,
    details: dict[str, Any] | None = None,
) -> ToolError | None:
    """Return a :class:`ToolError` when ``exc`` is a known ticket error.

    Returns ``None`` when the exception is not a recognised iRODS ticket
    error, so callers can fall through to their existing handling rather
    than mislabelling an unrelated failure as a ticket problem.

    ``details`` deliberately does **not** receive the ticket string: a
    ticket is a bearer capability, and error payloads are the part of a
    response most likely to be logged and aggregated.
    """
    code = irods_error_code(exc)
    if code is None or code not in TICKET_ERRORS:
        return None

    name, tool_code, hint = TICKET_ERRORS[code]
    payload: dict[str, Any] = {"irods_error": name, "irods_code": code}
    if details:
        payload.update(details)
    return ToolError(
        code=tool_code,
        message=f"{context}: {hint}",
        details=payload,
    )
