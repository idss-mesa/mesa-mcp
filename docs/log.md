# Directory Update Log

## 2026-11-24

* **Creation**: Published the documentation as a Zensical site at
  https://idss-mesa.github.io/mesa-mcp/ with an Open Knowledge Format (OKF v0.2)
  bundle: frontmatter on every page, [llms.txt](llms.txt) and
  [llms-full.txt](llms-full.txt), a Markdown twin of every page, and the shared
  idss-mesa scripts (`okf_validate.py`, `gen_llms_txt.py`,
  `postbuild_agent_surface.py`, `okf_common.py`). Added the
  [home page](index.md), section listings, [For AI agents](about/ai-agents.md), this
  log, `docs/agent-questions.yml`, `AGENTS.md`, and `.github/workflows/docs.yml`.
* **Creation**: Added [DuckLake integration](dev/ducklake-integration.md) (why
  mesa-ducklake runs in-process, the AVU-write mirror path, MCP tools versus the
  Python API) and [DataCite metadata](user/datacite.md).
* **Update**: Regenerated the [Tools reference](user/tools-reference.md) from the
  registry: 52 tools, adding `ds_add_avus`, `mesa_ducklake_time_travel` and the four
  DataCite tools that were missing.
* **Update**: Rewrote [Metadata workflows](user/examples.md) (formerly "Examples"),
  [Architecture](dev/architecture.md), [Adding tools](dev/adding-tools.md),
  [Testing](dev/testing.md) and [Configuration](user/configuration.md) to match the
  code: the HTTP transport, `/healthz`, the DuckLake facade, `mesa_avu_apply_term`,
  `mesa_ducklake_time_travel`, the `mesa_mcp.tools` plugin entry point, the CI jobs,
  honoured OLS TTLs, and warn-and-ignore handling of unknown config keys.
* **Update**: Corrected stale "planned" or "not implemented" statements in the
  deploy pages, the OLS internals page and the getting-started and install pages, and
  pointed install commands and repository links at `idss-mesa/mesa-mcp` and
  `idss-mesa/mesa-ducklake`, the organisation the MESA installer clones from.
* **Update**: Links from pages to source files now use absolute GitHub URLs, because
  the strict site build rejects links that leave `docs/`. Local machine paths in the
  DataCite plan were replaced with generic ones.
