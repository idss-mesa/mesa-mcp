# Design records

Design records for mesa-mcp features: the context that prompted a change, the decision taken, and the trade-offs weighed, plus historical implementation plans.

* [DataCite support (design)](2026-06-08-datacite-support-design.md) - Why and how mesa-mcp gained DataCite 4.x descriptive-metadata tools, modelled on the OLS pattern.
* [DataCite support (plan)](plans/2026-06-08-datacite-support.md) - The task-by-task plan that implemented it; historical, so trust the code and tests over its checkboxes.

## Conventions

- Design records sit at this level; read one before changing the feature it covers.
- `plans/` keeps step-by-step plans for their historical value. Once a plan is implemented its checkboxes are not maintained.
- These documents used to live under `docs/superpowers/` and followed the "superpowers" skill convention (plans opened with a `REQUIRED SUB-SKILL` header). That convention is deprecated; don't add those headers to new documents.
- New plans are produced with Claude Code plan mode and the project sub-agents under [`.claude/`](https://github.com/idss-mesa/mesa-mcp/tree/main/.claude). Commit a plan here only when it has lasting design value. Name files `YYYY-MM-DD-<topic>.md`.
