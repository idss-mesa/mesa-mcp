# AGENTS.md

Instructions for coding agents (Codex, opencode, goose, Claude Code and
others). [`CLAUDE.md`](CLAUDE.md) has the goals, design decisions and
reference repositories; read it for anything non-trivial. Where CLAUDE.md
and the code disagree, the code wins.

## What this repo is

`mesa-mcp` is a Python (3.11+) MCP server for the CyVerse Data Store
(iRODS). It registers 52 built-in tools in these families:

- `ds_*`: iRODS files, AVUs, ACLs, tickets, rules and policies. Names and
  input shapes match the Go
  [cyverse/irods-mcp-server](https://github.com/cyverse/irods-mcp-server).
- `mesa_ols_*` / `mesa_avu_*`: EMBL-EBI OLS ontology browsing, and writing
  terms as AVUs.
- `mesa_datacite_*` / `mesa_avu_apply_datacite`: DataCite 4.x records as
  AVUs.
- `mesa_ducklake_*`: per-project AVU history, kept by
  [idss-mesa/mesa-ducklake](https://github.com/idss-mesa/mesa-ducklake),
  which is imported in-process as the optional `ducklake` extra.
- `mesa_policy_*`: toggle MESA project policies (AVUs on a project root).

## Commands

```bash
pip install -e ".[dev]"                     # install (dev extras)
pytest -q                                   # full suite (hermetic; read the skip summary)
pytest tests/test_ds_avu_tools.py -q        # one file
ruff check src/ tests/                      # lint (CI gate; line length 100)
mypy src/                                   # types (advisory in CI)

# Real mesa-ducklake (tests/test_config_active.py skips without it):
pip install "mesa-ducklake @ git+https://github.com/idss-mesa/mesa-ducklake@main"
pip install -e ".[dev,ducklake]"

# Keep a local ~/.irods out of the tests:
IRODS_ENVIRONMENT_FILE=/nonexistent IRODS_AUTHENTICATION_FILE=/nonexistent pytest -q

# Run the server:
mesa-mcp --transport stdio                  # or --transport sse, --config FILE

# Docs (Python 3.11+): validate, regenerate llms.txt, build
pip install zensical pyyaml
python scripts/okf_validate.py docs
python scripts/gen_llms_txt.py
zensical build --clean --strict && python scripts/postbuild_agent_surface.py site
```

## Hard contracts

- **AVU shape is `(attribute, value, unit)`.** Ontology AVUs are
  `attribute=<ontology_id lowercased>.<snake_case label>`, `value` as
  supplied, `unit=<term CURIE>`, the shape esiil-portal writes. Use the
  helpers in `ols/client.py` (`_label_to_snake`) and `ols/transform.py`;
  never add fields to the triple.
- **`ds_*` wire parity.** A tool that exists in irods-mcp-server keeps its
  name, description and input schema byte for byte.
- **Path safety.** Every tool that takes a path calls
  `irods.access.assert_allowed(path, auth_value)` and uses the returned
  path.
- **Mirror AVU writes.** A tool that writes AVUs to a path calls
  `ducklake.client.record_avu_change` (or `record_avu_changes` for one
  snapshot per user action) after the iRODS write succeeds, and reports a
  mirror failure as `partial_failure`, not an error.
- **Narrow mesa-ducklake boundary.** Only `src/mesa_mcp/ducklake/`
  imports `mesa_ducklake`, always lazily inside functions, so mesa-mcp
  still runs without the extra.
- **Structured errors.** Raise `errors.ToolError(code, message, details)`;
  never let a traceback or a credential reach the client or the logs.
- **MCP 2026-07-28 on SDK 2.x.** No 1.x decorator API, no `sampling`,
  `roots` or `logging/setLevel` (CI greps for them).
- **Docs ship with code.** Update the affected page under `docs/`, keep
  OKF frontmatter on every page, and commit the regenerated
  `docs/llms.txt` and `docs/llms-full.txt` (CI checks for drift). Do not
  edit the shared `scripts/okf_*.py`, `gen_llms_txt.py` or
  `postbuild_agent_surface.py`; change `zensical.toml` instead.

## Where things live

- `src/mesa_mcp/`: `server.py` (registry, plugins, dispatch), `config.py`,
  `auth/`, `transport/` (HTTP, OIDC), `irods/`, `ols/`, `datacite/`,
  `ducklake/`. Tools live in each area's `tools/` package, one module per
  tool, auto-imported. Third-party tools register through the
  `mesa_mcp.tools` entry-point group.
- `tests/`: pytest, `asyncio_mode = "auto"`; `tests/irods/` and
  `tests/transport/` mirror those packages.
- `deploy/`: systemd unit, nginx site and installers for the hosted
  service.
- `docs/`: published at https://idss-mesa.github.io/mesa-mcp/.
  `docs/user/` (install, configuration, tools reference, metadata
  workflows, DataCite), `docs/dev/` (architecture, DuckLake integration,
  adding tools, testing, contributing), `docs/deploy/`, `docs/design/`.
  `docs/agent-questions.yml` lists questions the docs must answer.
- `.claude/agents/`: Claude Code sub-agents (`irods-tool-porter`,
  `ols-tool-author`, `mcp-reviewer`); their playbooks are plain Markdown
  and useful to any agent.
