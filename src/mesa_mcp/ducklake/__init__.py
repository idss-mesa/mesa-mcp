"""DuckLake integration package.

Thin client into the sibling project `cyverse/mesa-ducklake`_, which stores
AVU history per project (Postgres catalog + Parquet under
``/.mesa/ducklake/`` in each iRODS project collection).

See ``CLAUDE.md`` section "DuckLake integration" for the design and
``mesa_mcp.ducklake.client`` for the in-process facade.

.. _cyverse/mesa-ducklake: https://github.com/cyverse/mesa-ducklake
"""
