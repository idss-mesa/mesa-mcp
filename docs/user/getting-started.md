# Getting started

What this page covers: installing mesa-mcp from source, supplying iRODS
credentials, and confirming the server is responsive by calling the built-in
`ds_ping` tool. mesa-mcp is in pre-alpha — most `ds_*` tools are not yet
implemented, but the transport, configuration, and tool registry are working
end-to-end.

## Requirements

- Python 3.11 or newer.
- A POSIX shell (the project is developed on Ubuntu 24.04 with Bash 5).
- Network access to the EMBL-EBI OLS API
  (`https://www.ebi.ac.uk/ols4/api`) if you want the `mesa_ols_*` tools to
  succeed.
- A CyVerse iRODS account is **not** required to exercise `ds_ping` or any
  of the `mesa_ols_*` / `mesa_avu_*` tools that ship today. The full `ds_*`
  iRODS tool surface is in progress.

## Install

Clone the repo and create a virtualenv. mesa-mcp ships as a standard
`pyproject.toml`-driven package and installs in editable mode for
development.

```bash
git clone https://github.com/cyverse/mesa-mcp.git
cd mesa-mcp
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The `[dev]` extras pull in `pytest`, `pytest-asyncio`, `pytest-mock`,
`ruff`, `mypy`, and the typing stubs used in CI. To install the runtime
only, drop the `[dev]` suffix.

## Configure

mesa-mcp's configuration precedence is `flag > env > YAML > defaults`. The
recommended pattern is a small `config.yaml` checked in (or templated) for
non-secret settings, with secrets injected via environment variables.

```bash
cp config.yaml.example config.yaml
cp .env.example .env
```

Edit `config.yaml` to point at the iRODS host you want to talk to (the
default is `data.cyverse.org`). Edit `.env` to supply
`MESA_MCP_IRODS__PASSWORD` if you are not using the `anonymous` user.

The full list of fields lives in [configuration](./configuration.md).

## Run the server

mesa-mcp speaks the MCP wire protocol over stdio. The most common usage is
to launch it from an MCP client (Claude Desktop, Claude Code, Inspector,
etc.); see [Claude Desktop wiring](./claude-desktop.md) for sample client
configs.

To launch the server standalone for a smoke test:

```bash
source .env  # exports MESA_MCP_* into the shell
mesa-mcp --config config.yaml
```

You will not see any output: stdio-mode servers write only MCP frames on
`stdout`, and there is nothing to send until a client connects. Press
`Ctrl-C` to shut down.

To check the package installed correctly, run:

```bash
mesa-mcp --version
mesa-mcp --help
```

`--version` prints the running mesa-mcp version. `--help` prints the
argparse-driven CLI surface (currently `--config`, `--transport`,
`--log-level`).

## Smoke-test with the MCP Inspector

The MCP Inspector (`npx @modelcontextprotocol/inspector`) is the easiest way
to verify mesa-mcp end-to-end without wiring a real client. With the
Inspector pointed at `mesa-mcp --config config.yaml` you should see
`ds_ping` in the tool list. Call it with no arguments and the response is:

```json
{"pong": "ok", "version": "0.1.0"}
```

Pass `{"message": "hello"}` to see the echo path:

```json
{"pong": "hello", "version": "0.1.0"}
```

`ds_ping` requires no iRODS connectivity — if it fails, the problem is in
the transport, not in mesa-mcp's iRODS layer.

## What's next

- Wire mesa-mcp into your MCP client of choice — see
  [Claude Desktop wiring](./claude-desktop.md).
- Browse the ontology side: see [Examples](./examples.md) for an end-to-end
  OBO/OLS flow.
- Adjust caching, transport, or DuckLake settings via the
  [configuration reference](./configuration.md).

## See also

- [Configuration](./configuration.md)
- [Tools reference](./tools-reference.md)
- [Claude Desktop / Claude Code wiring](./claude-desktop.md)
- [`../../README.md`](../../README.md) — top-level repository README.
