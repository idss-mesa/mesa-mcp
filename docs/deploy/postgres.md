---
type: Guide
title: Postgres
description: 'Provision a Postgres database for the mesa-ducklake catalog behind mesa-mcp''s AVU history: role and database, migrations, the catalog_dsn, backups, and the DuckDB-file alternative.'
tags:
- deploy
- postgres
- mesa-ducklake
generated:
  by: claude/opus-5.5
  at: '2026-11-24T00:00:00Z'
sources:
- id: facade
  resource: https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/ducklake/client.py
  title: DuckLake facade
  author: team:idss-mesa
- id: ducklake-postgres
  resource: https://github.com/idss-mesa/mesa-ducklake/blob/main/docs/deploy/postgres.md
  title: mesa-ducklake Postgres deployment
  author: team:idss-mesa
status: stable
stale_after: '2027-02-24T00:00:00Z'
---

# Postgres

What this page covers: provisioning a local Postgres instance to host
the `mesa_ducklake` catalog database for the sibling library
[`idss-mesa/mesa-ducklake`](https://github.com/idss-mesa/mesa-ducklake),
which records the AVU history. mesa-mcp does not own the schema: it
imports mesa-ducklake in-process through the facade in
[`src/mesa_mcp/ducklake/client.py`](https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/ducklake/client.py)
and hands it the DSN (see [DuckLake integration](../dev/ducklake-integration.md)).

Postgres is the catalog for hosted, multi-writer deployments. A single
local process can use a DuckDB file instead
(`duckdb:///abs/path/catalog.duckdb`), with no server to run. mesa-ducklake's
[`docs/deploy/postgres.md`](https://github.com/idss-mesa/mesa-ducklake/blob/main/docs/deploy/postgres.md)
is the source of truth for schema-level setup.

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

You should see at least the default `public` schema. The catalog schema
belongs to mesa-ducklake. Apply its migrations with its CLI, which is
idempotent:

```bash
MESA_DUCKLAKE_DSN=postgresql://mesa:…@127.0.0.1:5432/mesa_ducklake mesa-ducklake migrate
```

Do not run it against the iCAT database.

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

If `catalog_dsn` is unset or empty (the default), or the `ducklake`
extra is not installed, mesa-mcp's AVU-write tools still succeed; they
just do not mirror to the history, and the `mesa_ducklake_*` tools fail
with `ducklake_disabled`.

## Backups

The catalog rows are small and important. mesa-ducklake ships the backup
pipeline: `deploy/backup-pg.sh` with a `mesa-ducklake-backup.service` and
`.timer` pair that runs a daily `pg_dump` and pushes it into iRODS. See
its [`docs/deploy/backup.md`](https://github.com/idss-mesa/mesa-ducklake/blob/main/docs/deploy/backup.md).
After a restore, run `mesa-ducklake migrate` to apply any newer schema.

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
- [`../../CLAUDE.md`](https://github.com/idss-mesa/mesa-mcp/blob/main/CLAUDE.md) — DuckLake integration section.
- [DuckLake integration](../dev/ducklake-integration.md) — how mesa-mcp
  uses the catalog.
- [idss-mesa/mesa-ducklake](https://github.com/idss-mesa/mesa-ducklake) —
  the library; its `docs/deploy/` covers Postgres, the DuckDB and Quack
  catalogs, backups and iRODS rules.
