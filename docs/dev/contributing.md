---
type: Guide
title: Contributing
description: 'How to land a change in mesa-mcp: branch and PR conventions, pre-flight checks, the three Claude Code sub-agents, security rules, and how to edit, validate and publish these OKF docs.'
tags:
- contributing
- pull-requests
- docs
generated:
  by: claude/opus-5.5
  at: '2026-11-24T00:00:00Z'
sources:
- id: agents
  resource: https://github.com/idss-mesa/mesa-mcp/tree/main/.claude/agents
  title: Claude Code sub-agents
  author: team:idss-mesa
- id: docs-workflow
  resource: https://github.com/idss-mesa/mesa-mcp/blob/main/.github/workflows/docs.yml
  title: Documentation workflow
  author: team:idss-mesa
status: stable
stale_after: '2027-05-24T00:00:00Z'
---

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
python -c "
import mesa_mcp.server as s
for spec in sorted(s.get_registered_tools(), key=lambda t: t.name):
    print(spec.name)
"
```

Your tool name should appear in the alphabetical output.

## The three Claude Code sub-agents

mesa-mcp ships three Claude Code sub-agents under
[`.claude/agents/`](https://github.com/idss-mesa/mesa-mcp/tree/main/.claude/agents) that automate the bulk of
the porting and review workflow. Each one has a focused remit and a
detailed playbook. Invoke them from Claude Code with the `Agent` tool.

### `irods-tool-porter`

[`/.claude/agents/irods-tool-porter.md`](https://github.com/idss-mesa/mesa-mcp/blob/main/.claude/agents/irods-tool-porter.md)

Use this agent to port a single MCP tool (or a batch of related ones)
from the Go reference,
[cyverse/irods-mcp-server](https://github.com/cyverse/irods-mcp-server),
into mesa-mcp. (The agent's playbook expects a local checkout at a
path you may need to adjust.) The agent reads the
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

[`/.claude/agents/ols-tool-author.md`](https://github.com/idss-mesa/mesa-mcp/blob/main/.claude/agents/ols-tool-author.md)

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

[`/.claude/agents/mcp-reviewer.md`](https://github.com/idss-mesa/mesa-mcp/blob/main/.claude/agents/mcp-reviewer.md)

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

Documentation lives under `docs/` and is published with
[Zensical](https://zensical.org/) to https://idss-mesa.github.io/mesa-mcp/
by `.github/workflows/docs.yml`. The source is an Open Knowledge Format
(OKF v0.2) bundle, so:

- Every page except `index.md` files and `log.md` starts with YAML
  frontmatter: `type`, `title`, a one-line `description` (it becomes the
  page's entry in `llms.txt`, so keep it accurate), `generated: {by, at}`,
  optional `sources`, and `status` (`draft`, `stable` or `deprecated`).
- Section `index.md` files carry no frontmatter; the root `docs/index.md`
  declares only `okf_version` and site keys.
- New pages go into the `nav` in `zensical.toml`, or they are not built
  and not listed in `llms.txt`.
- Record notable documentation changes in `docs/log.md` under a
  `## YYYY-MM-DD` heading.
- Link to other pages with relative `.md` paths. Link to source files
  with full `https://github.com/idss-mesa/mesa-mcp/blob/main/...` URLs:
  the strict build rejects links that leave `docs/`.
- `docs/agent-questions.yml` lists questions the published docs must
  answer. If a change removes an answer, update the page or the question.

Before pushing a docs change (Python 3.11+):

```bash
pip install zensical pyyaml
python scripts/okf_validate.py docs           # frontmatter conformance
python scripts/gen_llms_txt.py                # regenerate docs/llms.txt and llms-full.txt
zensical build --clean --strict               # must build without warnings
python scripts/postbuild_agent_surface.py site
```

Commit the regenerated `docs/llms.txt` and `docs/llms-full.txt`; CI
fails the pull request when they differ from a fresh run. The scripts in
`scripts/` (`okf_common.py`, `okf_validate.py`, `gen_llms_txt.py`,
`postbuild_agent_surface.py`) are shared across idss-mesa sites and read
everything site-specific from `zensical.toml`; change the config, not
the scripts. `site/` is build output and is not committed.

## Security and credentials

- Never commit `.env` or a populated `config.yaml`. They are
  `.gitignore`-d.
- Never log a password. `AuthValue` marks the field `repr=False` for
  this reason.
- Token storage (when persistence lands) uses AES-256-GCM with
  scrypt-derived keys — the pattern from `cyverse/terrain-mcp`.
- Don't introduce new dependencies without discussion. The dependency
  surface (see [`pyproject.toml`](https://github.com/idss-mesa/mesa-mcp/blob/main/pyproject.toml)) is small on
  purpose.

## Issue triage

Open issues against the
[idss-mesa/mesa-mcp](https://github.com/idss-mesa/mesa-mcp/issues) repo.
The goals and recorded decisions are in
[CLAUDE.md](https://github.com/idss-mesa/mesa-mcp/blob/main/CLAUDE.md).

## See also

- [Architecture](./architecture.md)
- [Adding tools](./adding-tools.md)
- [Porting from Go](./porting-from-go.md)
- [OLS internals](./ols-internals.md)
- [Testing](./testing.md)
- [`.claude/agents/irods-tool-porter.md`](https://github.com/idss-mesa/mesa-mcp/blob/main/.claude/agents/irods-tool-porter.md)
- [`.claude/agents/ols-tool-author.md`](https://github.com/idss-mesa/mesa-mcp/blob/main/.claude/agents/ols-tool-author.md)
- [`.claude/agents/mcp-reviewer.md`](https://github.com/idss-mesa/mesa-mcp/blob/main/.claude/agents/mcp-reviewer.md)
