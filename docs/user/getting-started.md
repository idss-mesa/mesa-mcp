---
type: Guide
title: Getting started
description: Choose a mesa-mcp deployment mode (local, CyVerse VICE app, or hosted), install locally in a minute, see the credential order at a glance, and what works without iRODS or the AVU history.
tags:
- getting-started
- install
generated:
  by: claude/opus-5.5
  at: '2026-11-24T00:00:00Z'
sources:
- id: readme
  resource: https://github.com/idss-mesa/mesa-mcp/blob/main/README.md
  title: mesa-mcp README
  author: team:idss-mesa
- id: extract
  resource: https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/auth/extract.py
  title: Credential resolution
  author: team:idss-mesa
status: stable
stale_after: '2027-05-24T00:00:00Z'
---

# Getting started

What this page covers: a quick decision tree so you can find the page
that fits your situation. mesa-mcp is deployed in three modes — pick the
one that matches what you actually want to do, then follow the link.

## Pick your mode

| If you want to...                                                    | Read this                                          |
| -------------------------------------------------------------------- | -------------------------------------------------- |
| Connect to a shared mesa-mcp instance run by an operator (Mode A)    | [`./hosted-mcp.md`](./hosted-mcp.md)               |
| Operate a shared mesa-mcp instance yourself (Mode A)                 | [`../deploy/overview.md`](../deploy/overview.md)   |
| Install mesa-mcp on your laptop and call it from Claude Desktop / Claude Code / Cline / Continue (Mode B) | [`./local-install.md`](./local-install.md)         |
| Install mesa-mcp inside a CyVerse Discovery Environment VICE app — JupyterLab, RStudio Server, Cloud Shell (Mode C) | [`./vice-apps.md`](./vice-apps.md)                 |

This page itself focuses on **Mode B (local install)** because it has the
fewest moving parts. If you are unsure, start here and graduate to one of
the other pages once you know what shape of deployment you want.

## Mode B in 60 seconds

```bash
python3 -m venv ~/.venvs/mesa-mcp
~/.venvs/mesa-mcp/bin/pip install git+https://github.com/idss-mesa/mesa-mcp.git

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
  (`https://www.ebi.ac.uk/ols4/api/v2`) if you want the `mesa_ols_*` tools
  to succeed.
- For any `ds_*` tool that touches iRODS: a CyVerse account with iRODS
  credentials. The `ds_ping` liveness tool and every `mesa_ols_*` /
  `mesa_avu_from_term` tool work without iRODS.

## Configuring credentials at a glance

mesa-mcp resolves iRODS credentials once at stdio startup, in this
order:

1. **Explicit settings**: `MESA_MCP_IRODS_USER` / `MESA_MCP_IRODS_PASSWORD`
   (single underscore), or `irods.user` / `irods.password` from
   `MESA_MCP_IRODS__USER` / `MESA_MCP_IRODS__PASSWORD` (double
   underscore) or a YAML file passed with `--config`. These win when a
   non-anonymous user is set together with a password.
2. **`~/.irods/irods_environment.json` + `~/.irods/.irodsA`**, written by
   `iinit`. mesa-mcp reads your username, zone, host, port and the
   descrambled password directly. The standard `IRODS_ENVIRONMENT_FILE` /
   `IRODS_AUTHENTICATION_FILE` overrides apply.
3. **Anonymous**: read-only access to the public shared tree.

The full configuration reference is in [`./configuration.md`](./configuration.md).

## What works today

- `ds_ping` — liveness check, no auth required.
- The six `mesa_ols_*` tools and `mesa_avu_from_term` — talk to the
  public OLS API, no iRODS required. The DataCite template, validate and
  export tools need no iRODS either.
- The `ds_*` iRODS tool surface — full CRUD on data objects, AVUs,
  ACLs, plus ticket lifecycle and rule execution. Requires iRODS auth.
- `mesa_avu_apply_term` and `mesa_avu_apply_datacite` — write AVUs and
  record them in the AVU history. The history half is skipped silently
  if `ducklake.catalog_dsn` is empty, which is the default in Mode B.
- `mesa_ducklake_init_project`, `mesa_ducklake_history` and
  `mesa_ducklake_time_travel` — need `ducklake.catalog_dsn` and the
  `ducklake` extra.

For the full list, see [`./tools-reference.md`](./tools-reference.md).

## What's next

- Wire mesa-mcp into your MCP client of choice — see
  [`./claude-desktop.md`](./claude-desktop.md) for JSON snippets for
  Claude Desktop, Claude Code, Cline, and Continue.
- Try the [metadata workflows](./examples.md): AVU search, ontology
  terms, history and tickets.
- Adjust caching, transport, or DuckLake settings via the
  [configuration reference](./configuration.md).

## See also

- [Local install](./local-install.md) — the full Mode B walkthrough.
- [VICE app install](./vice-apps.md) — Mode C inside a CyVerse VICE app.
- [Deployment overview](../deploy/overview.md) — Mode A hosted topology.
- [Configuration](./configuration.md)
- [Tools reference](./tools-reference.md)
- [MCP client wiring](./claude-desktop.md)
- [`../../README.md`](https://github.com/idss-mesa/mesa-mcp/blob/main/README.md) — top-level repository README.
