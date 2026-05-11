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
