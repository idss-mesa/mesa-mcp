# Contributing

What this page covers: how to land a change in mesa-mcp — branch
naming, PR scope, the review workflow (including the three Claude Code
sub-agents that automate much of it), and what reviewers will check
before merging.

## Getting set up

See [Getting started](../user/getting-started.md) for the
install-from-source path. Once the dev extras are installed (`pip
install -e ".[dev]"`), you have `pytest`, `ruff`, and `mypy` on your
`PATH`.

## Branch and PR conventions

- One conceptual change per PR. Tool ports (`ds_list_directory`,
  `ds_read_file`) land one or two at a time, not in mega-batches.
- Branch names: `feat/<short-slug>`, `fix/<short-slug>`,
  `port/<tool-name>`, `docs/<page>`.
- Commit messages: imperative present tense, ≤ 70 character subject,
  body explains the *why*.
- Always create new commits — never amend or force-push to a shared
  branch.

## Pre-flight checklist

Before opening a PR:

```bash
ruff check src/ tests/
mypy src/
pytest -q
```

If anything is red, fix it. CI will reject the PR otherwise.

Also confirm your tool registered, if you added one:

```bash
.venv/bin/python -c "
import mesa_mcp.server
import mesa_mcp.ols
try:
    import mesa_mcp.irods.tools
except Exception:
    pass
for spec in sorted(mesa_mcp.server.get_registered_tools(), key=lambda s: s.name):
    print(spec.name)
"
```

Your tool name should appear in the alphabetical output.

## The three Claude Code sub-agents

mesa-mcp ships three Claude Code sub-agents under
[`.claude/agents/`](../../.claude/agents/) that automate the bulk of
the porting and review workflow. Each one has a focused remit and a
detailed playbook. Invoke them from Claude Code with the `Agent` tool.

### `irods-tool-porter`

[`/.claude/agents/irods-tool-porter.md`](../../.claude/agents/irods-tool-porter.md)

Use this agent to port a single MCP tool (or a batch of related ones)
from the Go reference at
`/home/exouser/irods-mcp-server/` into mesa-mcp. The agent reads the
matching `irods/<tool>.go` file as the spec and produces:

- A Pydantic input model matching the Go JSON Schema byte-for-byte.
- An async handler calling `python-irodsclient` via the connection
  pool.
- Path-access enforcement via `mesa_mcp.irods.access.assert_allowed`.
- A unit test in `tests/irods/test_<tool>.py`.
- DuckLake recording hook for write-side tools (when the project is
  MESA-enabled).

Invoke it for any `ds_*` work. The agent's playbook embeds the
Go-to-Python translation table — see
[Porting from Go](./porting-from-go.md) for the same table in
narrative form.

### `ols-tool-author`

[`/.claude/agents/ols-tool-author.md`](../../.claude/agents/ols-tool-author.md)

Use this agent for any OBO/OLS / ontology work — porting code from
`esiil-portal`, authoring `mesa_ols_*` or `mesa_avu_*` tools, debugging
term resolution, or working with the AVU transform. The agent knows:

- The OLS4 API surface and the v1/v2 split.
- The frozen AVU shape contract (`attribute=<ontology>.<snake>`,
  `unit=<CURIE>`, value free-form) so portal-written and mesa-written
  AVUs interoperate.
- How to strip Django dependencies from ported code (replace `django.
  core.cache` with `cachetools.TTLCache`).

Invoke it before you hand-edit `ols/client.py` or `ols/transform.py`.

### `mcp-reviewer`

[`/.claude/agents/mcp-reviewer.md`](../../.claude/agents/mcp-reviewer.md)

A **read-only** reviewer. Use this agent before opening any non-trivial
PR. It produces a structured report covering:

1. MCP wire-format parity with `irods-mcp-server` (name, description,
   input schema, output shape — every byte).
2. iRODS correctness — path-access enforcement, session-pool usage,
   collection-vs-data-object distinction, AVU shape.
3. OLS / AVU shape — the canonical attribute/unit contract, round-trip
   with `ols_transform.py`.
4. DuckLake recording on write paths (skipping silently when the
   project is not MESA-enabled).
5. Security hygiene — no credentials in logs, AES-256-GCM for any
   persisted tokens, no `print()` calls.
6. Test coverage — every new tool has a unit test, path-access has a
   negative test, OLS code has a round-trip test.

The reviewer's output is a markdown report with **Blocking issues**,
**Non-blocking concerns**, **Confirmed correct**, and **Suggestions**
sections. Address blocking issues before merging.

## Documentation changes

Documentation lives under `docs/` (you are here). Every doc page opens
with a "What this page covers" paragraph and ends with a "See also"
list. Cross-link with relative paths. Keep each page under ~400 lines;
split if it grows.

Do not auto-generate API docs into this tree — `docs/` is plain
GitHub-flavored Markdown intended to be read in a browser without a
build step. There is no `mkdocs.yml`.

## Security and credentials

- Never commit `.env` or a populated `config.yaml`. They are
  `.gitignore`-d.
- Never log a password. `AuthValue` marks the field `repr=False` for
  this reason.
- Token storage (when persistence lands) uses AES-256-GCM with
  scrypt-derived keys — the pattern from `cyverse/terrain-mcp`.
- Don't introduce new dependencies without discussion. The dependency
  surface (see [`pyproject.toml`](../../pyproject.toml)) is small on
  purpose.

## Issue triage

Open issues against the
[cyverse/mesa-mcp](https://github.com/cyverse/mesa-mcp) repo. Tag with
`ds:*` (iRODS), `ols:*` (OBO/OLS), `mesa:*` (DuckLake), or
`infra:*` (transport, OIDC, deploy). The roadmap lives in
[`../../CLAUDE.md`](../../CLAUDE.md).

## See also

- [Architecture](./architecture.md)
- [Adding tools](./adding-tools.md)
- [Porting from Go](./porting-from-go.md)
- [OLS internals](./ols-internals.md)
- [Testing](./testing.md)
- [`.claude/agents/irods-tool-porter.md`](../../.claude/agents/irods-tool-porter.md)
- [`.claude/agents/ols-tool-author.md`](../../.claude/agents/ols-tool-author.md)
- [`.claude/agents/mcp-reviewer.md`](../../.claude/agents/mcp-reviewer.md)
