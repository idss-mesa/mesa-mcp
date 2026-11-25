# Develop

How mesa-mcp is built, how it uses mesa-ducklake, how to add a tool, and how it is tested.

* [Architecture](architecture.md) - The process layout, tool registry and plugins, transports, authentication, and the iRODS, OLS, DataCite and DuckLake subsystems.
* [DuckLake integration](ducklake-integration.md) - Why mesa-ducklake runs in-process, how each AVU write is mirrored into the history, and which history operations are MCP tools.
* [Adding tools](adding-tools.md) - Add a tool with `@register_tool`, or ship tools from another package through the `mesa_mcp.tools` entry point.
* [Testing](testing.md) - Run the hermetic test suite and linters, mock iRODS, OLS and mesa-ducklake, and what each CI job checks.
* [Contributing](contributing.md) - Branch and PR conventions, pre-flight checks, the Claude Code sub-agents, and how to edit and publish these docs.
* [Porting from Go](porting-from-go.md) - Port a `ds_*` tool from cyverse/irods-mcp-server with a byte-for-byte matching wire shape.
* [OLS internals](ols-internals.md) - The OLS client, its caches and retries, and the frozen AVU contract shared with esiil-portal.
