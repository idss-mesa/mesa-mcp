# Postgres

What this page covers: provisioning a local Postgres instance to host
the `mesa_ducklake` catalog database that the sibling project
[`cyverse/mesa-ducklake`](https://github.com/cyverse/mesa-ducklake)
needs. mesa-mcp does not own the schema — it only connects through the
DuckLake facade. The DuckLake integration in mesa-mcp itself is
**planned**; today the `DuckLakeClient` in
[`src/mesa_mcp/ducklake/client.py`](../../src/mesa_mcp/ducklake/client.py)
is a stub that raises `NotImplementedError`. This page describes how
to have Postgres ready for when the implementation lands.

For mesa-ducklake's own deployment specifics, cross-reference its
`docs/deploy/postgres.md` (in the sibling repo) once that file
exists.

## What mesa-ducklake needs

A vanilla Postgres 15+ instance with:

- A dedicated user (`mesa`) with a password and `LOGIN` privilege.
- A database named `mesa_ducklake` owned by that user.
- Connectivity from the mesa-mcp process — most simply over the local
  Unix socket, alternatively over `127.0.0.1:5432`.

The catalog rows are small (one per project root); the bulk Parquet
data lives **inside iRODS** under `<project>/.mesa/ducklake/`, not in
Postgres.

## Install Postgres on Ubuntu 24.04

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql
```

Ubuntu 24.04 ships Postgres 16. Postgres 15 is fine too. The default
`postgresql.service` unit listens on `127.0.0.1:5432` and on the Unix
socket under `/var/run/postgresql/`.

## Create the user and database

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE mesa LOGIN PASSWORD 'replace-me-with-strong-secret';
CREATE DATABASE mesa_ducklake OWNER mesa;
GRANT ALL PRIVILEGES ON DATABASE mesa_ducklake TO mesa;
SQL
```

Verify:

```bash
sudo -u postgres psql -d mesa_ducklake -c '\dn'
```

You should see at least the default `public` schema. The DuckLake
schema migrations are owned by mesa-ducklake; run them per its docs
when that repo lands.

## DSN for `mesa-mcp` config

Set `ducklake.catalog_dsn` (or
`MESA_MCP_DUCKLAKE__CATALOG_DSN`) to the Postgres DSN. Examples:

```yaml
ducklake:
  catalog_dsn: postgresql://mesa:replace-me-with-strong-secret@127.0.0.1:5432/mesa_ducklake
  data_collection: .mesa/ducklake
```

Or as an env var (the recommended path so the secret stays out of
YAML):

```bash
MESA_MCP_DUCKLAKE__CATALOG_DSN=postgresql://mesa:replace-me-with-strong-secret@/mesa_ducklake?host=/var/run/postgresql
```

The trailing `?host=/var/run/postgresql` connects via the Unix socket
when mesa-mcp runs as `exouser` on the same VM — avoids password
transit over loopback. Postgres's `peer` authentication can be enabled
in `pg_hba.conf` to skip the password entirely for that case; whether
to do so is a deployment choice.

## Leaving DuckLake disabled

If you set `catalog_dsn` to an empty string (the default), mesa-mcp's
AVU-write tools still succeed — they just **don't** mirror to
DuckLake. This is the recommended setting until mesa-ducklake is
ready.

## Backups

The catalog rows are small and important. The recommended pattern,
cribbed from the esiil-portal deployment on the same VM:

- A `pg_dump --format=custom mesa_ducklake` cron / systemd timer.
- Rotate dumps to `/media/volume/portal_db/backups/` (or wherever the
  VM has spare disk).
- Test the restore yearly.

A starter `mesa-mcp-pg-backup.timer` + `.service` pair will live in
the repo's `install/` directory once the DuckLake integration lands.

## Why Postgres specifically

DuckLake's catalog needs an ACID-compliant SQL backend; Postgres is
the canonical choice and is already in use across CyVerse for iCAT.
mesa-ducklake design notes call this out explicitly:

> Catalog: Postgres (same engine iRODS iCAT uses; one Postgres
> instance can host both if desired).

If the VM already runs Postgres for esiil-portal or another service,
adding the `mesa_ducklake` database to the same cluster is fine.

## See also

- [Overview](./overview.md)
- [`../user/configuration.md`](../user/configuration.md) for the
  `ducklake.catalog_dsn` field.
- [`../../CLAUDE.md`](../../CLAUDE.md) — DuckLake integration section.
- [`src/mesa_mcp/ducklake/client.py`](../../src/mesa_mcp/ducklake/client.py)
  — the stub facade today.
- [cyverse/mesa-ducklake](https://github.com/cyverse/mesa-ducklake) —
  sibling repo. Once it ships, its `docs/deploy/postgres.md` is the
  source of truth for schema-level setup.
