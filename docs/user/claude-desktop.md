# MCP client wiring

What this page covers: how to register mesa-mcp with the four MCP
clients people most often pair with it — Anthropic's Claude Desktop,
Anthropic's Claude Code, Cline (VS Code), and Continue (VS Code /
JetBrains). All four launch mesa-mcp as a stdio subprocess; the JSON
shape is the same in each case, but the config-file location and the
key names differ.

The HTTP/SSE transport (Mode A) uses a different connection model — the
client points at a URL and a bearer token rather than launching a
subprocess. See [`../deploy/http-sse.md`](../deploy/http-sse.md) when
that mode is what you want.

## Pre-flight

Confirm mesa-mcp runs from your shell first:

```bash
~/.venvs/mesa-mcp/bin/mesa-mcp --version
```

If that prints a version number, the binary is launchable and the
clients below will be able to spawn it. Always reference the absolute
path to the venv-installed entry point in client configs — MCP clients
launch subprocesses without inheriting your interactive shell's `$PATH`
(notably true on macOS).

## Claude Desktop

Claude Desktop reads MCP server definitions from
`~/Library/Application Support/Claude/claude_desktop_config.json` on
macOS and `%APPDATA%\Claude\claude_desktop_config.json` on Windows. Add
an `mcpServers` entry:

```json
{
  "mcpServers": {
    "mesa-mcp": {
      "command": "/Users/alice/.venvs/mesa-mcp/bin/mesa-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "MESA_MCP_IRODS__USER": "alice",
        "MESA_MCP_IRODS__ZONE": "iplant",
        "MESA_MCP_IRODS__HOST": "data.cyverse.org",
        "MESA_MCP_IRODS__PASSWORD": "hunter2"
      }
    }
  }
}
```

Restart Claude Desktop. The mesa-mcp tools should appear in the tools
picker. Try `ds_ping` first to confirm the wire is alive.

Notes:

- Prefer the absolute path to the venv-installed entry point — Claude
  Desktop launches subprocesses without inheriting your shell's PATH.
- Secrets go in the `env` block, not in a YAML on disk.
- If you do not see the tools after restart, check
  `~/Library/Logs/Claude/mcp*.log` on macOS for stderr from the
  mesa-mcp process.

## Claude Code

Claude Code supports per-project MCP servers via `.mcp.json` in your
project root and user-scoped servers via `~/.claude/settings.json`. The
easiest path is `claude mcp add`:

```bash
claude mcp add mesa-mcp \
  --transport stdio \
  --command /home/alice/.venvs/mesa-mcp/bin/mesa-mcp \
  --args "--transport,stdio" \
  --env MESA_MCP_IRODS__USER=alice \
  --env MESA_MCP_IRODS__ZONE=iplant \
  --env MESA_MCP_IRODS__PASSWORD=...
```

Or hand-edit `.mcp.json`:

```json
{
  "mcpServers": {
    "mesa-mcp": {
      "command": "/home/alice/.venvs/mesa-mcp/bin/mesa-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "MESA_MCP_IRODS__USER": "alice",
        "MESA_MCP_IRODS__ZONE": "iplant",
        "MESA_MCP_IRODS__PASSWORD": "..."
      }
    }
  }
}
```

Reload the workspace (or restart `claude`). The tools are available to
the agent on the next prompt. Inside a CyVerse VICE pod (Mode C), the
exact same `.mcp.json` works — just point `command` at the in-pod venv
(`/home/jovyan/.venvs/mesa-mcp/bin/mesa-mcp` for JupyterLab) and rely
on the inherited shell env for credentials.

## Cline (VS Code)

Cline reads MCP server definitions from VS Code's settings — the
extension surfaces a UI under "Cline → MCP Servers" but writes the
underlying config to its own JSON file at
`~/.vscode/extensions/.../cline_mcp_settings.json` (path varies by
release; the UI is the supported entry point). The structure is the
same `mcpServers` map:

```json
{
  "mcpServers": {
    "mesa-mcp": {
      "command": "/home/alice/.venvs/mesa-mcp/bin/mesa-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "MESA_MCP_IRODS__USER": "alice",
        "MESA_MCP_IRODS__ZONE": "iplant",
        "MESA_MCP_IRODS__PASSWORD": "..."
      }
    }
  }
}
```

Use Cline's "Refresh MCP Servers" action after saving. The extension
surfaces stderr from the subprocess in the VS Code Output pane under
the Cline channel.

## Continue (VS Code / JetBrains)

Continue stores MCP server definitions in `~/.continue/config.json` (or
`%USERPROFILE%\.continue\config.json` on Windows) under the
`experimental.modelContextProtocolServers` key in older releases or the
top-level `mcpServers` key in newer ones. Consult
[continue.dev/docs](https://docs.continue.dev/) for the version you are
on; the value shape is identical:

```json
{
  "mcpServers": {
    "mesa-mcp": {
      "command": "/home/alice/.venvs/mesa-mcp/bin/mesa-mcp",
      "args": ["--transport", "stdio"],
      "env": {
        "MESA_MCP_IRODS__USER": "alice",
        "MESA_MCP_IRODS__ZONE": "iplant",
        "MESA_MCP_IRODS__PASSWORD": "..."
      }
    }
  }
}
```

Reload the Continue extension. Tool calls are logged to the Output pane.

## MCP Inspector

For an interactive, GUI-driven smoke test of mesa-mcp's tool surface
without wiring a real client:

```bash
npx @modelcontextprotocol/inspector \
  /home/alice/.venvs/mesa-mcp/bin/mesa-mcp \
  --transport stdio
```

The Inspector opens a local browser tab showing the registered tools and
lets you invoke them with arbitrary input. Useful when you are debugging
a hand-written Pydantic input model.

## Anonymous-only quick start

If you do not yet have a CyVerse account, mesa-mcp still ships the
`mesa_ols_*` tools and `mesa_avu_from_term`, which only talk to the
public OLS API. Drop the `MESA_MCP_IRODS__*` env entries and the
server still starts fine — you simply will not be able to use any `ds_*`
tools that need authenticated iRODS access (and `ds_ping` requires no
auth anyway).

## See also

- [Local install](./local-install.md) — Mode B install walkthrough.
- [VICE app install](./vice-apps.md) — Mode C in-pod install.
- [Getting started](./getting-started.md)
- [Configuration](./configuration.md)
- [Tools reference](./tools-reference.md)
- [Examples](./examples.md)
- [Deployment — HTTP/SSE](../deploy/http-sse.md) for the hosted-service
  transport.
