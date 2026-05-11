# VICE app install (Mode C)

What this page covers: installing mesa-mcp inside a CyVerse Discovery
Environment **VICE app** — JupyterLab, RStudio Server, or Cloud Shell —
so an in-pod MCP client (typically Claude Code running in the same pod)
can call it. This is the recommended path when you are already working
inside a VICE session and want agent access to your CyVerse Data Store
files without standing up a hosted service.

If you instead want a local-on-laptop install, read
[`./local-install.md`](./local-install.md) (Mode B). For the shared
hosted service with bearer-token auth, read
[`../deploy/overview.md`](../deploy/overview.md) (Mode A).

## Why this mode is useful

- **Your iRODS auth is already mounted.** The VICE container launcher
  drops `~/.irods/irods_environment.json` and `~/.irods/.irodsA` into the
  pod with your CyVerse identity, and the iCommands CLI is pre-installed
  and authenticated. You do not type a password.
- **Private and shared paths "just work."** `/iplant/home/<you>/` is
  fully read/write. `/iplant/home/shared/<project>/` is whatever iRODS
  ACLs grant you (own / write / read).
- **No public endpoint.** mesa-mcp runs as a stdio subprocess inside the
  pod. No nginx, no OIDC, no Keycloak client to register.
- **Per-user isolation comes for free.** Every VICE pod is its own user;
  no shared state to worry about.

## Prerequisites

- A CyVerse account.
- A running VICE app on the [CyVerse Discovery
  Environment](https://de.cyverse.org/). Any of the standard interactive
  apps works:
  - JupyterLab (home is `/home/jovyan/`)
  - RStudio Server (home is `/home/rstudio/`)
  - Cloud Shell (home is `~` for whatever user the image runs as)
- A terminal inside the VICE app. JupyterLab has the launcher tile,
  RStudio has the Terminal pane, Cloud Shell is itself a terminal.
- Confirm the iRODS env is mounted:

  ```bash
  ls ~/.irods/                                    # should show irods_environment.json and .irodsA
  ils /iplant/home/$(jq -r .irods_user_name ~/.irods/irods_environment.json)
  ```

  If `ils` returns a listing, your iRODS identity is live in the pod.

## One-shot install

Paste this into the VICE terminal. It installs mesa-mcp into a venv
under your home, populates the iRODS env vars from the iRODS env file,
and launches the server.

```bash
python3 -m venv ~/.venvs/mesa-mcp
~/.venvs/mesa-mcp/bin/pip install git+https://github.com/cyverse/mesa-mcp.git

# Pull iRODS settings out of the env file the VICE launcher dropped in.
IRODS_ENV=~/.irods/irods_environment.json
export MESA_MCP_IRODS__USER=$(jq -r .irods_user_name "$IRODS_ENV")
export MESA_MCP_IRODS__ZONE=$(jq -r .irods_zone_name "$IRODS_ENV")
export MESA_MCP_IRODS__HOST=$(jq -r .irods_host "$IRODS_ENV")
export MESA_MCP_IRODS__PORT=$(jq -r .irods_port "$IRODS_ENV")

# Password — see "Authentication options" below for the three approaches.
# Quickest path: re-run iinit to get a fresh plaintext-in-memory.
iinit
export MESA_MCP_IRODS__PASSWORD=...   # plaintext you just typed into iinit

~/.venvs/mesa-mcp/bin/mesa-mcp --transport stdio
```

The server stays silent (stdio frames only) until a client connects.
`Ctrl-C` to exit.

## Authentication options inside a VICE pod

The VICE pod always has `~/.irods/irods_environment.json` (with username
/ zone / host / port populated) and `~/.irods/.irodsA` (scrambled
password). Today you still need to land the password into
`MESA_MCP_IRODS__PASSWORD` by one of three routes:

1. **Re-prompt with `iinit`.** Type your CyVerse password once; copy it
   into the env var. The plaintext lives only in your shell's memory.
   Easy, but you re-type on every pod launch.
2. **Use the scrambled `.irodsA` directly (future-work).** python-iRODSclient
   already decodes `.irodsA` automatically when a session is constructed
   without explicit credentials; mesa-mcp does not yet wire that path
   through its config loader. When it lands, you will be able to leave
   `MESA_MCP_IRODS__PASSWORD` unset and mesa-mcp will read the scrambled
   file just like `ils` does. Track this in the project issues if it
   blocks you.
3. **Service-account env injection.** Some VICE app configurations bind
   a service identity into the container's environment (for example,
   automated batch workflows). When that is the case, set
   `MESA_MCP_IRODS__USER` and `MESA_MCP_IRODS__PASSWORD` from the
   orchestrator-provided env (`$IRODS_USER_NAME`, etc.) instead of
   re-running `iinit`.

## What you can access from inside mesa-mcp

Inside the pod your iRODS identity is whatever
`irods_environment.json -> irods_user_name` says. mesa-mcp's
`assert_allowed` path-check lets through:

- `/iplant/home/<your-username>/...` — your private home directory.
  Full read / write / delete / AVU.
- `/iplant/home/shared/<project>/...` — community and shared
  collections. Whatever iRODS ACLs grant you (own / write / read).

`assert_allowed` is a soft gate — it confirms the path falls within the
caller's accessible-path set (home + shared + any ticket-granted paths).
The hard enforcement happens inside iRODS itself: ACLs reject ops on
shared subpaths where you do not have `write` / `own`, regardless of
what `assert_allowed` allowed. This is the correct layering — see
[`../dev/architecture.md`](../dev/architecture.md) for the model.

## Wire mesa-mcp into Claude Code (in-pod)

Claude Code is the natural in-pod MCP client because the iRODS env vars
are already exported in your shell. In your project, create
`.mcp.json` (or run `claude mcp add`):

```json
{
  "mcpServers": {
    "mesa": {
      "command": "/home/jovyan/.venvs/mesa-mcp/bin/mesa-mcp",
      "args": ["--transport", "stdio"]
    }
  }
}
```

Substitute the right home directory — `/home/jovyan` for JupyterLab,
`/home/rstudio` for RStudio Server, whatever `echo $HOME` says in Cloud
Shell. The env vars set in your shell are inherited by the subprocess
mesa-mcp runs under.

For a JupyterLab notebook-style MCP client (or any in-pod agent
runtime), the JSON shape is the same — the `command` field points at
the venv-installed binary, and the env is inherited from the parent
process.

## Connecting from a laptop MCP client to a VICE-hosted mesa-mcp

If you want Claude Desktop / Cline / Continue on your laptop to talk to
mesa-mcp running in a VICE pod, **do not** ssh-tunnel stdio. The right
answer is the **SSE transport** — which is the deployment pattern
described in [`../deploy/overview.md`](../deploy/overview.md). In short:
spin up mesa-mcp as a hosted service (Mode A), front it with nginx +
Let's Encrypt, and use CyVerse Keycloak OIDC for per-user
authentication. Your laptop MCP client points at the public HTTPS URL
with a bearer token.

This is exactly the trade-off Mode A exists for: laptop clients +
remote server demands a real transport, not an SSH bodge over stdio.
See [`../deploy/overview.md`](../deploy/overview.md) and
[`../deploy/oidc.md`](../deploy/oidc.md).

## Limitations and footguns

- **VICE pods are ephemeral.** The venv lives only for the lifetime of
  the pod. Capture the install into a shell script in your CyVerse
  home (`/iplant/home/<you>/scripts/install-mesa-mcp.sh` or
  `~/scripts/install-mesa-mcp.sh` if you store it in the pod's home and
  it survives via the CyVerse home mount) and re-run it after each
  launch.
- **DuckLake history is off by default in this mode.** There is no
  Postgres in the pod, so `MESA_MCP_DUCKLAKE__CATALOG_DSN` stays empty
  and `mesa_avu_apply_term` short-circuits the mirror step silently. To
  enable history, point that DSN at a remote Postgres catalog you
  control — see [mesa-ducklake's docs](https://github.com/cyverse/mesa-ducklake/tree/main/docs).
- **Egress matters.** The OLS tools talk to
  `https://www.ebi.ac.uk/ols4/api`. This works as long as the VICE pod's
  network policy allows outbound HTTPS to `www.ebi.ac.uk` — which is the
  default at the time of writing.
- **Auth bound to your user.** Because the pod runs as your CyVerse
  identity, mesa-mcp cannot impersonate another user from inside it.
  Mode A (hosted service + OIDC + service-account or proxy auth) is the
  multi-user story.

## See also

- [Getting started](./getting-started.md) — the cross-mode entry page.
- [Local install](./local-install.md) — Mode B on your laptop.
- [MCP client wiring](./claude-desktop.md)
- [Configuration](./configuration.md)
- [Deployment overview](../deploy/overview.md) — Mode A topology.
- [CyVerse Discovery Environment](https://de.cyverse.org/) — launch
  point for VICE apps.
