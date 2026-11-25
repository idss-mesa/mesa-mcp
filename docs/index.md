---
okf_version: "0.2"
title: mesa-mcp
description: "mesa-mcp is a Model Context Protocol (MCP) server for the CyVerse Data Store (iRODS) that adds ontology-driven AVU metadata from the EMBL-EBI Ontology Lookup Service, DataCite records, and a per-project AVU history kept by mesa-ducklake."
---

# mesa-mcp

**mesa-mcp** is a [Model Context Protocol](https://modelcontextprotocol.io/)
server that gives AI agents the CyVerse Data Store (iRODS). Its main tool
families are:

- **`ds_*`**: files, folders, AVU metadata, access control, tickets, rules
  and policies. Names and inputs match
  [cyverse/irods-mcp-server](https://github.com/cyverse/irods-mcp-server),
  so clients can swap servers.
- **`mesa_ols_*` and `mesa_avu_*`**: browse ontologies in the EMBL-EBI
  [Ontology Lookup Service](https://www.ebi.ac.uk/ols4/) and write a
  chosen term as an AVU, with the term's CURIE in the `unit` slot. This is
  the same AVU shape the esiil-portal metadata UI writes.
- **`mesa_datacite_*`**: DataCite 4.x records as AVUs, with validation and
  XML export for DOI requests.
- **`mesa_ducklake_*`**: the AVU history of every file and folder in a
  MESA-enabled project, with time travel. The history is kept by
  [mesa-ducklake](https://github.com/idss-mesa/mesa-ducklake), which
  mesa-mcp imports in-process; every AVU change made through mesa-mcp is
  mirrored into it.

Two `mesa_policy_*` tools toggle MESA project policies. There are 52
built-in tools. mesa-mcp is written in Python (3.11+) on the
MCP Python SDK 2.x and targets the MCP 2026-07-28 specification. It runs
over `stdio` for local clients, or as an HTTP service (old-style SSE and
Streamable HTTP) behind CyVerse Keycloak.

## Install in one minute

```bash
python3 -m venv ~/.venvs/mesa-mcp
~/.venvs/mesa-mcp/bin/pip install git+https://github.com/idss-mesa/mesa-mcp.git
claude mcp add mesa-mcp -s user -- ~/.venvs/mesa-mcp/bin/mesa-mcp --transport stdio
```

If you have run `iinit`, mesa-mcp picks up your CyVerse credentials from
`~/.irods/`; otherwise it runs as the read-only `anonymous` user. Ask your
agent to call `ds_ping` to confirm it is connected. The MESA installer in
[idss-mesa/docs](https://idss-mesa.github.io/docs/) sets up mesa-mcp,
mesa-ducklake and the other MESA servers for several agent clients at
once.

## Documentation

* [Use mesa-mcp](user/index.md) - Install it (local, CyVerse VICE, or hosted), connect a client, configure it, and the tools and metadata workflows.
* [Develop](dev/index.md) - Architecture, the DuckLake integration, adding tools, testing, and contributing.
* [Deploy](deploy/index.md) - Run mesa-mcp as a shared HTTP service: systemd, nginx and TLS, CyVerse Keycloak OIDC, Postgres, and monitoring.
* [Design records](design/index.md) - Why larger features are shaped the way they are, with historical plans.
* [About](about/index.md) - How AI agents should read this site, and the documentation changelog.

This site is an [Open Knowledge Format (OKF) v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
bundle: every page carries YAML frontmatter with its type, provenance and
status. Agents can read the whole corpus at [`llms.txt`](llms.txt) and
[`llms-full.txt`](llms-full.txt); see [For AI agents](about/ai-agents.md).

## Where to get help

* Bugs and feature requests: [GitHub issues](https://github.com/idss-mesa/mesa-mcp/issues).
* The wider MESA stack: [MESA documentation](https://idss-mesa.github.io/docs/).
