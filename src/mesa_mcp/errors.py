"""Structured error types for mesa-mcp tools.

Every tool handler should raise :class:`ToolError` for user-facing failures.
The MCP server boundary translates these into structured error payloads — we
never leak Python tracebacks to clients.
"""

from __future__ import annotations

from typing import Any


class ToolError(Exception):
    """A structured error raised from inside an MCP tool handler.

    Attributes
    ----------
    code:
        A short, stable, machine-friendly error code (e.g. ``"not_found"``,
        ``"permission_denied"``, ``"invalid_argument"``). Clients should be
        able to switch on it.
    message:
        Human-readable summary, safe to surface to end users. Must not contain
        credentials, tokens, or full file paths outside the user's access.
    details:
        Optional structured context. Keys are free-form; values must be
        JSON-serializable.
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details) if details else {}

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the error."""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"ToolError(code={self.code!r}, message={self.message!r})"


class InputRequired(Exception):
    """Raised by a handler that needs one more round-trip with the user.

    This is the mesa-mcp side of **Multi Round-Trip Requests** (MCP
    2026-07-28). The server boundary turns it into an
    ``InputRequiredResult`` carrying an ``elicitation/create`` form; the
    client presents the form, and its answer arrives on a follow-up
    ``tools/call`` as ``inputResponses`` plus the ``requestState`` string
    handed out here.

    Statelessness constraint
    ------------------------
    MRTR under the stateless core has no session to park a continuation
    in: ``request_state`` is a string that travels **out to the client and
    back**. Two consequences shape this class:

    * everything needed to resume must fit in ``state`` — a handler may
      not stash a continuation in process memory, because the follow-up
      call will routinely land on a different instance;
    * ``state`` is client-controlled by the time it returns, so the
      resumed handler must re-validate every value out of it. It carries
      *what was being asked*, never *what the caller may do* — no
      authorization decision belongs in it. Path access is re-checked on
      resume against the caller's live token, not trusted from state.

    Attributes
    ----------
    message:
        Prompt shown to the user alongside the choices.
    schema:
        JSON Schema (2020-12) describing the expected answer.
    state:
        JSON-serializable dict round-tripped through the client and handed
        back to the handler on resume.
    key:
        Identifier for this elicitation within the request; the client
        keys its response by the same string.
    """

    def __init__(
        self,
        message: str,
        schema: dict[str, Any],
        state: dict[str, Any],
        key: str = "elicitation",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.schema = dict(schema)
        self.state = dict(state)
        self.key = key
