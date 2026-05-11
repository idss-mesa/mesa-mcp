"""iRODS ticket lifecycle helpers.

The :class:`irods.ticket.Ticket` class from ``python-irodsclient`` is the
canonical surface for creating, modifying, and revoking iRODS tickets.
Its API is sparse — ``Ticket.issue(permission, target)``, ``Ticket.modify``,
``Ticket.delete``, and ``Ticket.supply`` — so the helpers here are thin
wrappers that translate mesa-mcp's structured input into the right
sequence of PRC calls.

PRC quirks worth knowing about:

* ``Ticket(session)`` with no ``ticket`` argument **auto-generates** a
  random 15-character alnum string. We rely on this for ``issue_ticket``.
* ``Ticket.modify`` takes a variable arg list whose first element is the
  attribute name (e.g. ``"uses"``, ``"expire"``, ``"add-host"``,
  ``"add-user"``, ``"write-bytes"``). The class auto-converts ``expire``
  values from human-readable timestamps to epoch seconds, but the
  human format it accepts is ``%Y-%m-%d.%H:%M:%S`` — *not* ISO-8601 —
  so we pre-convert ISO-8601 expiries before forwarding.
* ``Ticket.delete`` and ``Ticket.modify`` both perform an API request
  immediately; there is no transactional commit step.
* There is no ``Ticket.get_by_string`` constructor that fetches existing
  ticket metadata, so we look up an existing ticket through the
  ``TicketQuery.Ticket`` ICAT query when modifying or revoking.

Module-level helpers, kept free of MCP imports so tests can use them
directly.
"""

from __future__ import annotations

import calendar
import datetime
from typing import Any, Literal

from irods.models import TicketQuery
from irods.ticket import Ticket

TicketMode = Literal["read", "write"]


def _iso_to_pcr_timestamp(expiry: str) -> str:
    """Convert an ISO-8601 expiry into the format ``Ticket.modify`` accepts.

    PRC accepts either an integer epoch-seconds string *or* the format
    ``%Y-%m-%d.%H:%M:%S`` (UTC). We accept the user-friendly ISO-8601
    form (``2026-05-10T12:34:56Z`` and variants) and forward an
    epoch-seconds string, which PRC then parses as the integer branch.
    """
    # Normalise trailing 'Z' that fromisoformat doesn't accept until 3.11+.
    cleaned = expiry.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    return str(calendar.timegm(dt.utctimetuple()))


def issue_ticket(
    session: Any,
    path: str,
    mode: TicketMode,
    *,
    uses_allowed: int | None = None,
    expiry: str | None = None,
    write_byte_limit: int | None = None,
    host_restriction: str | None = None,
    user_restriction: str | None = None,
) -> dict[str, Any]:
    """Issue a fresh iRODS ticket and apply any optional restrictions.

    Returns a dict with the new ticket string plus echoed metadata, so
    callers (and the ``ds_create_ticket`` handler) can return both in
    one structured payload.
    """
    if mode not in ("read", "write"):
        raise ValueError(f"ticket mode must be 'read' or 'write', got {mode!r}")

    ticket = Ticket(session)
    ticket.issue(mode, path)

    applied: dict[str, Any] = {
        "ticket": ticket.string,
        "mode": mode,
        "path": path,
    }

    if uses_allowed is not None:
        ticket.modify("uses", str(int(uses_allowed)))
        applied["uses_allowed"] = int(uses_allowed)
    if expiry is not None:
        ticket.modify("expire", _iso_to_pcr_timestamp(expiry))
        applied["expiry"] = expiry
    if write_byte_limit is not None:
        if mode != "write":
            raise ValueError(
                "write_byte_limit only applies to write-mode tickets",
            )
        ticket.modify("write-bytes", str(int(write_byte_limit)))
        applied["write_byte_limit"] = int(write_byte_limit)
    if host_restriction is not None:
        ticket.modify("add", "host", host_restriction)
        applied["host_restriction"] = host_restriction
    if user_restriction is not None:
        ticket.modify("add", "user", user_restriction)
        applied["user_restriction"] = user_restriction

    return applied


def modify_ticket(
    session: Any,
    ticket_string: str,
    *,
    uses: int | None = None,
    expiry: str | None = None,
    write_byte_limit: int | None = None,
    host_restriction: str | None = None,
    user_restriction: str | None = None,
) -> dict[str, Any]:
    """Apply restriction changes to an existing ticket.

    Cannot change the ticket's mode — that's an iRODS-level invariant
    (issuing is a one-shot operation that bakes the mode into the
    ticket row). Callers should validate that ``mode`` is not in the
    input before calling.
    """
    ticket = Ticket(session, ticket=ticket_string)

    applied: dict[str, Any] = {"ticket": ticket_string}

    if uses is not None:
        ticket.modify("uses", str(int(uses)))
        applied["uses"] = int(uses)
    if expiry is not None:
        ticket.modify("expire", _iso_to_pcr_timestamp(expiry))
        applied["expiry"] = expiry
    if write_byte_limit is not None:
        ticket.modify("write-bytes", str(int(write_byte_limit)))
        applied["write_byte_limit"] = int(write_byte_limit)
    if host_restriction is not None:
        ticket.modify("add", "host", host_restriction)
        applied["host_restriction"] = host_restriction
    if user_restriction is not None:
        ticket.modify("add", "user", user_restriction)
        applied["user_restriction"] = user_restriction

    return applied


def revoke_ticket(session: Any, ticket_string: str) -> dict[str, Any]:
    """Delete an existing ticket. Returns a structured echo of the deletion."""
    ticket = Ticket(session, ticket=ticket_string)
    ticket.delete()
    return {"ticket": ticket_string, "deleted": True}


def lookup_ticket(session: Any, ticket_string: str) -> dict[str, Any] | None:
    """Return ICAT-recorded metadata for an existing ticket, or ``None``.

    Used by ``ds_get_ticket_info`` and as a sanity check before
    ``modify_ticket``. We expose the same column subset the Go server's
    ``TicketWithRestrictions`` exposes; the ``restrictions`` substructure
    is left empty for now (iRODS allowed-host/user/group tables require
    separate joins — see :class:`TicketQuery.AllowedHosts` etc.).
    """
    rows = list(
        session.query(TicketQuery.Ticket).filter(
            TicketQuery.Ticket.string == ticket_string,
        ),
    )
    if not rows:
        return None
    row = rows[0]
    ticket_id = row[TicketQuery.Ticket.id]
    return {
        "ticket": {
            "id": ticket_id,
            "string": row[TicketQuery.Ticket.string],
            "type": row[TicketQuery.Ticket.type],
            "user_id": row[TicketQuery.Ticket.user_id],
            "object_id": row[TicketQuery.Ticket.object_id],
            "object_type": row[TicketQuery.Ticket.object_type],
            "uses_limit": row[TicketQuery.Ticket.uses_limit],
            "uses_count": row[TicketQuery.Ticket.uses_count],
            "expiry_ts": row[TicketQuery.Ticket.expiry_ts],
            "write_byte_count": row[TicketQuery.Ticket.write_byte_count],
            "write_byte_limit": row[TicketQuery.Ticket.write_byte_limit],
            "write_file_count": row[TicketQuery.Ticket.write_file_count],
            "write_file_limit": row[TicketQuery.Ticket.write_file_limit],
        },
        "restrictions": _ticket_restrictions(session, ticket_id),
    }


def list_tickets(session: Any) -> list[dict[str, Any]]:
    """Return all tickets visible to the session's user."""
    results: list[dict[str, Any]] = []
    for row in session.query(TicketQuery.Ticket):
        ticket_id = row[TicketQuery.Ticket.id]
        results.append(
            {
                "ticket": {
                    "id": ticket_id,
                    "string": row[TicketQuery.Ticket.string],
                    "type": row[TicketQuery.Ticket.type],
                    "user_id": row[TicketQuery.Ticket.user_id],
                    "object_id": row[TicketQuery.Ticket.object_id],
                    "object_type": row[TicketQuery.Ticket.object_type],
                    "uses_limit": row[TicketQuery.Ticket.uses_limit],
                    "uses_count": row[TicketQuery.Ticket.uses_count],
                    "expiry_ts": row[TicketQuery.Ticket.expiry_ts],
                    "write_byte_count": row[TicketQuery.Ticket.write_byte_count],
                    "write_byte_limit": row[TicketQuery.Ticket.write_byte_limit],
                    "write_file_count": row[TicketQuery.Ticket.write_file_count],
                    "write_file_limit": row[TicketQuery.Ticket.write_file_limit],
                },
                "restrictions": _ticket_restrictions(session, ticket_id),
            },
        )
    return results


def _ticket_restrictions(session: Any, ticket_id: int) -> dict[str, list[str]]:
    """Read the allowed-host/user/group rows for a ticket id.

    Some PRC versions / iRODS schemas do not expose every restriction
    table — we swallow query errors per-table so listing tickets does
    not fail just because a server lacks the group restriction view.
    """
    out: dict[str, list[str]] = {"hosts": [], "users": [], "groups": []}

    for label, model, column in (
        ("hosts", TicketQuery.AllowedHosts, TicketQuery.AllowedHosts.host),
        ("users", TicketQuery.AllowedUsers, TicketQuery.AllowedUsers.user_name),
        ("groups", TicketQuery.AllowedGroups, TicketQuery.AllowedGroups.group_name),
    ):
        try:
            ticket_id_col = model.ticket_id
            rows = session.query(column).filter(ticket_id_col == str(ticket_id))
            out[label] = [row[column] for row in rows]
        except Exception:
            # Best-effort — different iRODS server versions expose
            # different restriction tables. Don't fail a ticket-info
            # lookup just because one column is missing.
            out[label] = []

    return out
