# Getting started

What this page covers: a quick decision tree so you can find the page
that fits your situation. mesa-mcp is deployed in three modes — pick the
one that matches what you actually want to do, then follow the link.

## Pick your mode

| If you want to...                                                    | Read this                                          |
| -------------------------------------------------------------------- | -------------------------------------------------- |
| Use a shared mesa-mcp instance run by an operator (Mode A)           | [`../deploy/overview.md`](../deploy/overview.md)   |
| Install mesa-mcp on your laptop and call it from Claude Desktop / Claude Code / Cline / Continue (Mode B) | [`./local-install.md`](./local-install.md)         |
| Install mesa-mcp inside a CyVerse Discovery Environment VICE app — JupyterLab, RStudio Server, Cloud Shell (Mode C) | [`./vice-apps.md`](./vice-apps.md)                 |

This page itself focuses on **Mode B (local install)** because it has the
fewest moving parts. If you are unsure, start here and graduate to one of
the other pages once you know what shape of deployment you want.

## Mode B in 60 seconds

```bash
python3 -m venv ~/.venvs/mesa-mcp
~/.venvs/mesa-mcp/bin/pip install git+https://github.com/cyverse/mesa-mcp.git

export MESA_MCP_IRODS__USER=alice
export MESA_MCP_IRODS__ZONE=iplant
export MESA_MCP_IRODS__HOST=data.cyverse.org
export MESA_MCP_IRODS__PASSWORD=...   # see local-install for options

~/.venvs/mesa-mcp/bin/mesa-mcp --transport stdio
```

The server stays silent because stdio-mode servers only emit MCP frames
when a client speaks first. Press `Ctrl-C` to exit.

Full prerequisites, alternative credential sources, smoke tests, and
troubleshooting are in [`./local-install.md`](./local-install.md).

## Requirements (common to all modes)

- Python 3.11 or newer.
- A POSIX shell (the project is developed on Ubuntu 24.04 with Bash 5;
  macOS Bash and Zsh are fine).
- Network access to the EMBL-EBI OLS API
  (`https://www.ebi.ac.uk/ols4/api`) if you want the `mesa_ols_*` tools
  to succeed.
- For any `ds_*` tool that touches iRODS: a CyVerse account with iRODS
  credentials. The `ds_ping` liveness tool and every `mesa_ols_*` /
  `mesa_avu_from_term` tool work without iRODS.

## Configuring credentials at a glance

mesa-mcp reads iRODS credentials in this precedence order (highest wins):

1. `MESA_MCP_IRODS_USER` / `MESA_MCP_IRODS_PASSWORD` (single-underscore
   form, ergonomic for ad-hoc CLI sessions).
2. `MESA_MCP_IRODS__USER` / `MESA_MCP_IRODS__PASSWORD` (canonical
   double-underscore form, used by env files and MCP-client configs).
3. The `irods.user` / `irods.password` keys in a YAML config file passed
   via `--config /path/to/config.yaml`.
4. The defaults — `user=anonymous`, `password=` (empty), which gives
   read-only public access.

mesa-mcp does **not** currently load credentials directly from
`~/.irods/.irodsA` (the scrambled-password file that `iinit` writes).
Today you copy values out of `~/.irods/irods_environment.json` into env
vars, and supply the password from somewhere else. Native loading of
`.irodsA` is tracked as future-work.

The full configuration reference is in [`./configuration.md`](./configuration.md).

## What works today

- `ds_ping` — liveness check, no auth required.
- All seven `mesa_ols_*` tools and `mesa_avu_from_term` — talk to the
  public OLS API, no iRODS required.
- The `ds_*` iRODS tool surface — full CRUD on data objects, AVUs,
  ACLs, plus ticket lifecycle and rule execution. Requires iRODS auth.
- `mesa_avu_apply_term` — composite tool that writes an AVU + records to
  DuckLake. The DuckLake half short-circuits silently if
  `ducklake.catalog_dsn` is empty, which is the default in Mode B.

For the full list, see [`./tools-reference.md`](./tools-reference.md).

## What's next

- Wire mesa-mcp into your MCP client of choice — see
  [`./claude-desktop.md`](./claude-desktop.md) for JSON snippets for
  Claude Desktop, Claude Code, Cline, and Continue.
- Browse the ontology side: see [`./examples.md`](./examples.md) for an
  end-to-end OBO/OLS flow.
- Adjust caching, transport, or DuckLake settings via the
  [configuration reference](./configuration.md).

## See also

- [Local install](./local-install.md) — the full Mode B walkthrough.
- [VICE app install](./vice-apps.md) — Mode C inside a CyVerse VICE app.
- [Deployment overview](../deploy/overview.md) — Mode A hosted topology.
- [Configuration](./configuration.md)
- [Tools reference](./tools-reference.md)
- [MCP client wiring](./claude-desktop.md)
- [`../../README.md`](../../README.md) — top-level repository README.
