"""iRODS integration package for mesa-mcp.

Modules:

* :mod:`mesa_mcp.irods.client_pool` — pooled ``iRODSSession`` objects keyed by
  caller identity. Mirrors the Go ``irods-mcp-server/irods/common/irodsfs_pool.go``
  pattern, with LRU eviction.
* :mod:`mesa_mcp.irods.access` — path-allowlist enforcement. Every ``ds_*``
  tool must call :func:`mesa_mcp.irods.access.assert_allowed` before invoking
  the iRODS backend.
* :mod:`mesa_mcp.irods.tools` — one module per ``ds_*`` tool, ported from the
  matching ``irods-mcp-server/irods/*.go`` file by the ``irods-tool-porter``
  agent.

See ``CLAUDE.md`` for the broader plan; :mod:`mesa_mcp.auth` for the
:class:`AuthValue` model these utilities consume.
"""
