# Design records

What this directory holds: design records for mesa-mcp features — the
context that prompted a change, the decision taken, and the trade-offs
weighed — plus the historical implementation plans that carried them out.

- `*.md` at this level are design records (specs). Read one before
  changing the feature it covers; it explains *why* the code is shaped
  the way it is.
- `plans/` holds step-by-step implementation plans kept for their
  historical value. Each is marked with its status; once implemented,
  its checkboxes are not maintained — trust the code and tests over a
  plan.

| Record | Plan |
| ------ | ---- |
| [DataCite support](./2026-06-08-datacite-support-design.md) | [plans/2026-06-08-datacite-support.md](./plans/2026-06-08-datacite-support.md) |

## Conventions

These documents previously lived under `docs/superpowers/` and followed
the "superpowers" skill convention: plans opened with a `REQUIRED
SUB-SKILL` header and were written and executed with
`superpowers:writing-plans`, `superpowers:executing-plans`, and
`superpowers:subagent-driven-development`. That convention is
deprecated; don't add those headers to new documents.

New step-by-step plans are produced with Claude Code plan mode and the
project subagents and skills under [`.claude/`](../../.claude/). Commit a
plan here only when it has lasting design value; routine plans stay in
the session that produced them. Name files `YYYY-MM-DD-<topic>.md`.
