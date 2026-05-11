# Security Review — 2026-05-11

Point-in-time review of the initial build of mesa-mcp and the sibling
mesa-ducklake. Covers commits `cyverse/mesa-mcp@5b7a5da` and
`cyverse/mesa-ducklake@896dce3` — roughly 10K lines of new Python plus
iRODS rule files and deployment artifacts.

Methodology mirrors the project's `/security-review` workflow: an
independent reviewer agent enumerated the attack surfaces below,
traced data flow end-to-end, then applied the project's false-positive
filter (confidence ≥ 8 to ship).

**Result: zero findings at confidence ≥ 8.**

## Attack surfaces examined

| # | Surface | File(s) | Verdict |
|---|---|---|---|
| 1 | OIDC JWT verification | `mesa-mcp/src/mesa_mcp/transport/oidc.py` | `algorithms` whitelist excludes `none`/HS\*; `exp`/`iss` always verified; `kid` matching; `PyJWK.from_dict` + PyJWT prevents RS256↔HS256 key confusion; optional `aud` is documented as such. |
| 2 | OIDC no-OIDC dev-mode fallback | `mesa-mcp/src/mesa_mcp/transport/sse.py:116-132` | Fallback constructs `AuthValue(auth_scheme="anonymous")`; iRODS server-side ACLs limit blast radius to the same scope as an unauthenticated WebDAV reader. Documented dev escape hatch. |
| 3 | Path-allowlist / prefix attacks | `mesa-mcp/src/mesa_mcp/irods/access.py` | `posixpath.normpath` clamps `..`; leading `//` collapsed; `is_within` appends `/` before prefix check, defeating `/foo/aliceX` ⊂ `/foo/alice`; allowed-root list also re-normalized. |
| 4 | SQL injection (Postgres + DuckDB) | `mesa-ducklake/src/mesa_ducklake/{catalog,lake,queries,schema}.py` | All Postgres queries use `%s` placeholders; DuckDB uses `?` placeholders; sole f-string into DuckDB (`lake.py:213-217`) escapes `'`→`''` over a fixed column tuple; migration runner only consumes numbered SQL files in the repo (trusted input). |
| 5 | iRODS GenQuery injection | `mesa-mcp/src/mesa_mcp/irods/tools/search_*.py` | All filters use PRC `Criterion`/`Like`; values travel as wire parameters, not concatenated SQL; `_shell_to_sql` escapes `%` and `_` in wildcards. |
| 6 | subprocess / shell exec | repo-wide | Only `mesa-ducklake/irods-rules/mesa_avu_change.py:34` calls `subprocess.run` — fixed argv, no `shell=True`, payload via `input=` kwarg. Server-side admin-installed code. |
| 7 | Pickle / unsafe deserialization | repo-wide | None. `json.loads` + `yaml.safe_load` only. |
| 8 | Ticket lifecycle authz | `mesa-mcp/src/mesa_mcp/irods/tools/{create,modify,delete}_ticket.py`, `irods/tickets.py` | Anonymous rejected at the tool layer; ownership/admin enforcement correctly delegated to the iRODS server. |
| 9 | `ds_execute_rule` | `mesa-mcp/src/mesa_mcp/irods/tools/execute_rule.py` | Designed surface; iRODS server gates what each authenticated user may execute. |
| 10 | `mesa_avu_apply_term` + DuckLake mirror | `mesa-mcp/src/mesa_mcp/ols/tools/avu_apply_term.py`, `mesa-mcp/src/mesa_mcp/ducklake/client.py` | Path through `assert_allowed`; AVU passed via `iRODSMeta`; mirror via Pydantic-validated `AvuChange` + parameterized writes. |
| 11 | YAML/JSON parsing | `mesa-mcp/src/mesa_mcp/config.py`, `mesa-ducklake/src/mesa_ducklake/cli.py` | `yaml.safe_load`; `json.loads` of stdin then Pydantic. |
| 12 | WebDAV URL minting | `mesa-mcp/src/mesa_mcp/irods/webdav.py` | Path split per segment + URL-encoded; username URL-encoded; netloc derived from validated `urlsplit`. |
| 13 | AuthValue / credential handling | `mesa-mcp/src/mesa_mcp/auth/` | Frozen Pydantic, `password` has `repr=False`; `cache_key` is SHA-256 over zone+user+password+proxy+ticket with unit-separator; no plaintext leak. |
| 14 | CLI JSON contract | `mesa-ducklake/src/mesa_ducklake/cli.py` | JSON via `json.loads`, body through Pydantic, SQL parameterized; not a remote interface. |

## Findings (confidence ≥ 8)

**None.**

## Observed but excluded per rubric

These are not vulnerabilities under the project's confidence-≥-8 bar.
They are recorded here so a future reviewer doesn't waste time
re-discovering them.

- **JSON-payload spoofing via AVU values in `mesa-ducklake/irods-rules/mesa_avu_change.re`.**
  Raw `msiStrCat` of user-controlled AVU strings into the JSON sent to
  `mesa-ducklake record`. Legitimate `actor`/`source` fields are written
  *after* user-controlled keys, and `json.loads` is last-key-wins, so
  the actor/source can't be spoofed. Worst case: a corrupted payload
  that the CLI rejects (non-zero exit) and the rule ignores. Excluded
  as "log spoofing via user input."
- **`mesa-ducklake/irods-rules/mesa_enroll_policy.re` GenQuery interpolation of `*parent`.**
  A collection-name containing `'` could perturb the auto-enroll check,
  but the only effect is to alter auto-enrollment of *the user's own*
  newly-created collection — a privilege the user already has via
  `ds_add_avu mesa.enabled=true`. No security boundary crossed.
- **`extract_from_headers` decodes JWT with `verify_signature=False`**
  at `mesa-mcp/src/mesa_mcp/auth/extract.py:91-150`. Exported but
  unwired; no production code path calls it. Latent risk if a future PR
  uses it without preserving the trusted-proxy assumption. Not
  currently exploitable.
- **No env-var gate on no-OIDC dev mode in `sse.py`** — only a startup
  `WARNING`. Practical blast radius is bounded by iRODS anonymous ACLs
  (see #2 above). Hardening rather than a vulnerability.

## Conclusion

The security-critical paths — JWT verification, path allow-listing,
parameterized SQL/DuckDB, AVU handling, credential representation —
are implemented carefully and consistently. No newly-introduced
exploitable vulnerability meets the confidence-≥-8 bar.

When in doubt, the next reviewer should re-run `/security-review`
against future commits and compare diffs against this baseline.
