# Claude Desktop and Claude Code wiring

What this page covers: how to register mesa-mcp with the two most common MCP
clients — Anthropic's Claude Desktop and Claude Code — so the tools light up
inside the assistant. mesa-mcp speaks the MCP stdio transport; both clients
launch the server as a subprocess and communicate over its stdin/stdout.

The HTTP/SSE transport is planned but not implemented yet; calling
`mesa-mcp --transport sse` raises `NotImplementedError`. Stick with stdio
for now.

## Pre-flight

Confirm mesa-mcp runs from your shell first:

```bash
mesa-mcp --version
```

If that prints a version number, the `mesa-mcp` console script is on your
`PATH` and the client below will be able to launch it. If not, either
activate the venv where you installed mesa-mcp or use the absolute path
(e.g. `/home/exouser/mesa-mcp/.venv/bin/mesa-mcp`) in the client config.

## Claude Desktop

Claude Desktop reads MCP server definitions from
`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS
and `%APPDATA%\Claude\claude_desktop_config.json` on Windows. Add a `mcpServers`
entry pointing at the mesa-mcp binary:

```json
{
  "mcpServers": {
    "mesa-mcp": {
      "command": "/home/exouser/mesa-mcp/.venv/bin/mesa-mcp",
      "args": ["--config", "/home/exouser/mesa-mcp/config.yaml"],
      "env": {
        "MESA_MCP_IRODS__USER": "alice",
        "MESA_MCP_IRODS__PASSWORD": "hunter2"
      }
    }
  }
}
```

Restart Claude Desktop. The mesa-mcp tools should now appear in the tools
picker. Try `ds_ping` first to confirm the wire is alive.

Notes:

- Prefer the absolute path to the venv-installed entry point — Claude
  Desktop launches subprocesses without inheriting your interactive shell's
  PATH on macOS.
- Secrets go in the `env` block, not in the YAML on disk.
- If you do not see the tools after restart, check
  `~/Library/Logs/Claude/mcp*.log` for stderr from the mesa-mcp process.

## Claude Code

Claude Code reads MCP server definitions from `.claude/settings.json` (or
the user-scoped `~/.claude/settings.json`). The same JSON snippet works:

```json
{
  "mcpServers": {
    "mesa-mcp": {
      "command": "/home/exouser/mesa-mcp/.venv/bin/mesa-mcp",
      "args": ["--config", "/home/exouser/mesa-mcp/config.yaml"],
      "env": {
        "MESA_MCP_IRODS__USER": "alice",
        "MESA_MCP_IRODS__PASSWORD": "hunter2"
      }
    }
  }
}
```

Reload the workspace (or restart `claude`). The tools should be available
to the agent on the next prompt.

## MCP Inspector

For an interactive, GUI-driven smoke test of mesa-mcp's tool surface,
launch the Inspector with the same command:

```bash
npx @modelcontextprotocol/inspector \
  /home/exouser/mesa-mcp/.venv/bin/mesa-mcp \
  --config /home/exouser/mesa-mcp/config.yaml
```

It opens a local browser tab showing the registered tools and lets you
invoke them with arbitrary input. Useful when you are debugging a
hand-written Pydantic input model.

## Anonymous-only quick start

If you do not yet have a CyVerse account, mesa-mcp still ships the
`mesa_ols_*` tools, which only talk to the public OLS API. Drop the
`MESA_MCP_IRODS__*` lines and the server still starts fine — you simply
will not be able to use any `ds_*` tools (and the only one shipping today,
`ds_ping`, requires no auth anyway).

## See also

- [Getting started](./getting-started.md)
- [Configuration](./configuration.md)
- [Tools reference](./tools-reference.md)
- [Examples](./examples.md)
- [Deployment — HTTP/SSE](../deploy/http-sse.md) for the planned remote
  transport.
