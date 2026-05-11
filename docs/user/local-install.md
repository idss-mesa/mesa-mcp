# Local install (Mode B)

What this page covers: installing mesa-mcp on your own workstation
(Linux or macOS) so an MCP client running on the same machine — Claude
Desktop, Claude Code, Cline, Continue — can launch it as a stdio
subprocess. No HTTP, no OIDC, no public hostname. iRODS auth is direct,
using your CyVerse username and password.

If you instead need a shared service that several users can connect to,
read [`../deploy/overview.md`](../deploy/overview.md) (Mode A). If you
work inside a CyVerse VICE app (JupyterLab, RStudio Server, Cloud
Shell), read [`./vice-apps.md`](./vice-apps.md) (Mode C).

## Prerequisites

- **Python 3.11 or newer.** Check with `python3 --version`.
- **An MCP client.** Any of:
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
  - [Claude Desktop](https://claude.ai/download)
  - [Cline](https://github.com/cline/cline) (VS Code extension)
  - [Continue](https://continue.dev/) (VS Code / JetBrains extension)
- **iRODS credentials.** Either:
  - the `iCommands` CLI installed and `iinit` already run, so you have a
    populated `~/.irods/irods_environment.json` (and the plaintext
    password on hand), or
  - the values you would have given to `iinit` — username, zone, host,
    port, password — in hand.

iCommands themselves are not strictly required to run mesa-mcp, but
having them installed is the easiest way to confirm your iRODS account
works before pointing mesa-mcp at the same credentials.

## Install

mesa-mcp is not yet on PyPI. Install from the git repository into a
dedicated virtualenv:

```bash
python3 -m venv ~/.venvs/mesa-mcp
~/.venvs/mesa-mcp/bin/pip install git+https://github.com/cyverse/mesa-mcp.git
```

If you prefer pipx-style isolation:

```bash
pipx install git+https://github.com/cyverse/mesa-mcp.git
# `mesa-mcp` will be on $PATH but lives in its own venv under ~/.local/pipx/venvs/.
```

Confirm the install:

```bash
~/.venvs/mesa-mcp/bin/mesa-mcp --version
~/.venvs/mesa-mcp/bin/mesa-mcp --help
```

The console script name is `mesa-mcp`. The published Python package
name is `mesa-mcp` as well; when PyPI publication happens this page will
swap `git+https://...` for `pip install mesa-mcp`.

## Configure iRODS credentials

There are three supported ways to feed credentials to mesa-mcp. Pick
whichever fits your workflow; all three feed the same `AuthValue` that
`assert_allowed` checks before every `ds_*` call.

### Option 1 — environment variables (recommended for MCP clients)

The cleanest path when your MCP client config supports an `env` block:

```bash
export MESA_MCP_IRODS__USER=alice
export MESA_MCP_IRODS__ZONE=iplant
export MESA_MCP_IRODS__HOST=data.cyverse.org
export MESA_MCP_IRODS__PORT=1247
export MESA_MCP_IRODS__PASSWORD=...
```

The double-underscore form (`MESA_MCP_IRODS__USER`) is the canonical
nested-config syntax. The single-underscore aliases
(`MESA_MCP_IRODS_USER`, `MESA_MCP_IRODS_PASSWORD`,
`MESA_MCP_IRODS_AUTH_SCHEME`, `MESA_MCP_IRODS_TICKET`,
`MESA_MCP_IRODS_PROXY_USER`) also work and take precedence over the
double-underscore form for `user`/`password` — useful when you want a
one-line override for an interactive shell session.

### Option 2 — copy out of `~/.irods/irods_environment.json`

If you have already run `iinit`, most of the values live in
`~/.irods/irods_environment.json`:

```bash
IRODS_ENV=~/.irods/irods_environment.json
export MESA_MCP_IRODS__USER=$(jq -r .irods_user_name "$IRODS_ENV")
export MESA_MCP_IRODS__ZONE=$(jq -r .irods_zone_name "$IRODS_ENV")
export MESA_MCP_IRODS__HOST=$(jq -r .irods_host "$IRODS_ENV")
export MESA_MCP_IRODS__PORT=$(jq -r .irods_port "$IRODS_ENV")
# The password lives in ~/.irods/.irodsA in scrambled form. For now you
# need the plaintext from CyVerse (or re-run `iinit` and type it). Native
# support for reading .irodsA is tracked as future-work.
export MESA_MCP_IRODS__PASSWORD=...
```

**Future-work:** mesa-mcp will read `~/.irods/.irodsA` directly via
python-irodsclient's built-in scrambled-password support, removing the
manual plaintext step above. The auth-scheme negotiation already handles
`native` and `pam` — what is missing is wiring the existing PRC helper
into the config loader. Track this in the project issues if you need it.

### Option 3 — YAML config file

For an MCP client config that does not let you set env vars, write a
small YAML file and point mesa-mcp at it with `--config`:

```bash
cp /path/to/mesa-mcp/config.yaml.example ~/.config/mesa-mcp/config.yaml
# edit ~/.config/mesa-mcp/config.yaml to fill in irods.user / irods.password
~/.venvs/mesa-mcp/bin/mesa-mcp --config ~/.config/mesa-mcp/config.yaml
```

The full field list is in [`./configuration.md`](./configuration.md). Do
not commit a `config.yaml` that contains a real password — the env-var
form is safer because the secret lives only in process memory.

## Smoke test

Run the server directly to confirm it boots:

```bash
~/.venvs/mesa-mcp/bin/mesa-mcp --transport stdio
```

You will see no output. This is correct: in stdio mode mesa-mcp only
writes MCP wire frames on `stdout`, and there is nothing to send until a
client connects. Press `Ctrl-C` to shut down.

For an interactive smoke test, use the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector \
  ~/.venvs/mesa-mcp/bin/mesa-mcp --transport stdio
```

It opens a local browser tab listing the registered tools. Call
`ds_ping` first — it requires no iRODS access, so a successful response
proves the wire is alive. Then try `ds_list_directory` against a path
under your CyVerse home to confirm iRODS auth is wired.

## Hook into an MCP client

The full JSON snippets for Claude Desktop, Claude Code, Cline, and
Continue live in [`./claude-desktop.md`](./claude-desktop.md). The
shape is the same in every case: point `command` at the venv-installed
binary, pass `--transport stdio` (the default), and put your iRODS
credentials in the `env` block.

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

## What works / what doesn't in local mode

- **Works.** The full `ds_*` iRODS surface (read, write, AVU, ACL, ticket
  lifecycle, rule execution, policy introspection), the seven `mesa_ols_*`
  tools, and `mesa_avu_from_term`.
- **Works with a caveat.** `mesa_avu_apply_term` writes the AVU to iRODS
  successfully, but the DuckLake mirror step short-circuits silently
  unless you have set `MESA_MCP_DUCKLAKE__CATALOG_DSN` to a reachable
  Postgres catalog. Most local users skip that — see
  [mesa-ducklake's docs](https://github.com/cyverse/mesa-ducklake/tree/main/docs).
- **Best-effort.** `ds_list_rules`, `ds_get_rule_definition`,
  `ds_list_policies`, and `ds_get_policy_config` return documented stub
  envelopes because python-irodsclient does not expose the underlying
  iRODS state to non-admin sessions. The `note` field in each response
  explains what was unavailable.

## Troubleshooting

- **`mesa-mcp: command not found`.** The venv's `bin/` is not on your
  `$PATH`. Use the absolute path, or activate the venv with
  `source ~/.venvs/mesa-mcp/bin/activate`.
- **`CAT_INVALID_AUTHENTICATION` from iRODS.** The password is wrong or
  the auth scheme is mismatched. CyVerse's hosted iRODS uses native
  auth — try `MESA_MCP_IRODS_AUTH_SCHEME=native` (and re-run `iinit` to
  re-verify the password if needed).
- **MCP client shows the server but no tools.** Some MCP clients launch
  subprocesses with a stripped `$PATH`. Use the absolute path to the
  venv-installed `mesa-mcp` binary, not the bare name.
- **`OLS request failed`.** Either network egress to
  `https://www.ebi.ac.uk/` is blocked, or OLS is having a bad afternoon.
  All `mesa_ols_*` tools retry with cached values where possible; check
  `MESA_MCP_OLS__BASE_URL` if you are forced through a proxy.
- **Where to look in logs.** mesa-mcp's stderr goes wherever the MCP
  client routes it. Claude Desktop on macOS writes to
  `~/Library/Logs/Claude/mcp*.log`; Claude Code writes to its
  per-session log under `~/.claude/`; Cline/Continue surface stderr in
  their VS Code Output panes.

## See also

- [Getting started](./getting-started.md) — the cross-mode entry page.
- [VICE app install](./vice-apps.md) — Mode C inside a CyVerse VICE app.
- [Deployment overview](../deploy/overview.md) — Mode A hosted topology.
- [MCP client wiring](./claude-desktop.md)
- [Configuration](./configuration.md)
- [Tools reference](./tools-reference.md)
- [Examples](./examples.md)
