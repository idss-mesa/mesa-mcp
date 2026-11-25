# Use mesa-mcp

Install mesa-mcp, connect an MCP client, configure it, and use its tools.

* [Getting started](getting-started.md) - Choose a deployment mode (local, CyVerse VICE, or hosted), install locally in a minute, and see what works without iRODS or the AVU history.
* [Local install](local-install.md) - Install mesa-mcp in a virtualenv on Linux or macOS, supply iRODS credentials (environment, `~/.irods` autodetection, or YAML), smoke-test it, and add the Croissant plugin.
* [VICE app install](vice-apps.md) - Run mesa-mcp inside a CyVerse Discovery Environment VICE app (JupyterLab, RStudio Server, Cloud Shell), reusing the pod's iRODS credentials.
* [Hosted mesa-mcp](hosted-mcp.md) - Connect desktop clients (through `mcp-remote` and a Keycloak JWT) or a claude.ai custom connector to a hosted mesa-mcp, verify it, and enroll a project.
* [MCP client wiring](claude-desktop.md) - Register a local stdio mesa-mcp with Claude Desktop, Claude Code, Cline, Continue and the MCP Inspector.
* [Configuration](configuration.md) - Every setting with its YAML key, `MESA_MCP_*` variable and default, the precedence rules, and how iRODS credentials are resolved.
* [Tools reference](tools-reference.md) - All 52 built-in tools with their input fields, defaults, outputs and errors.
* [Metadata workflows](examples.md) - Find files by AVU, tag data with ontology terms, write AVUs in bulk, read AVU history and time travel, and use tickets.
* [DataCite metadata](datacite.md) - Write, validate and export DataCite 4.x records stored as AVUs.
