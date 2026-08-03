#!/usr/bin/env python3
"""End-to-end check of the four access scenarios mesa-mcp must support.

Drives the **real** ``ds_*`` tool handlers -- not raw python-irodsclient --
so a pass here means the shipped tools work, not merely that iRODS does.

Scenarios
---------
1. **Public, unauthenticated.** The iRODS ``anonymous`` user reads a
   public collection under ``/<zone>/home/shared``.
2. **Private, as the user.** The authenticated caller reads their own
   home collection.
3. **Shared.** The authenticated caller reads a shared collection.
4. **Write.** The authenticated caller creates a collection, writes a
   file, reads it back, and cleans up.

Credentials
-----------
Standard iRODS chain: ``~/.irods/.irodsA`` (from ``iinit``), then
``MESA_MCP_IRODS_PASSWORD``, then an interactive ``getpass``. No
``--password`` flag -- argv is visible via ``ps``.

Usage
-----
    python3 scripts/check_access_scenarios.py \\
        --user tswetnam \\
        --public /iplant/home/shared/<a-public-collection> \\
        --shared /iplant/home/shared/cod

``--public`` should be a collection that genuinely has public read; it is
the only way to test scenario 1 honestly. Omit it to skip that check
rather than have it pass vacuously.

The report contains no secrets. Scenario 4 writes only inside a
temporary collection under your own home, and removes it afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

RESULT: dict[str, object] = {}


def _env_file_path() -> Path:
    return Path(
        os.environ.get(
            "IRODS_ENVIRONMENT_FILE",
            Path.home() / ".irods" / "irods_environment.json",
        )
    )


def _load_env_file() -> dict:
    path = _env_file_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _describe(exc: BaseException) -> str:
    """Report a failure precisely enough to tell a refusal from a bug."""
    from mesa_mcp.errors import ToolError
    from mesa_mcp.irods import ticket_errors

    if isinstance(exc, ToolError):
        return f"ToolError[{exc.code}] {exc.message}"
    code = ticket_errors.irods_error_code(exc)
    if code is not None and code in ticket_errors.TICKET_ERRORS:
        return f"{ticket_errors.TICKET_ERRORS[code][0]} (iRODS refusal)"
    return f"{type(exc).__name__}({exc})"


async def _run(args) -> None:
    from mesa_mcp.auth.models import ANONYMOUS_USER, AuthValue
    from mesa_mcp.config import Config, IRODSConfig
    from mesa_mcp.context import (
        current_auth_value,
        current_client_pool,
        current_config,
    )
    from mesa_mcp.irods.client_pool import IRODSClientPool
    from mesa_mcp.irods.tools.list_directory import (
        ListDirectoryInput,
        handle_list_directory,
    )
    from mesa_mcp.irods.tools.make_directory import (
        MakeDirectoryInput,
        handle_make_directory,
    )
    from mesa_mcp.irods.tools.read_file import ReadFileInput, handle_read_file
    from mesa_mcp.irods.tools.write_file import WriteFileInput, handle_write_file

    env = _load_env_file()
    host = env.get("irods_host") or "data.cyverse.org"
    port = int(env.get("irods_port") or 1247)
    zone = env.get("irods_zone_name") or "iplant"

    # --- credentials, most-secure first ---------------------------------
    irods_a = Path(
        os.environ.get("IRODS_AUTHENTICATION_FILE", Path.home() / ".irods" / ".irodsA")
    )
    password: str | None = os.environ.get("MESA_MCP_IRODS_PASSWORD")
    if password:
        source = "MESA_MCP_IRODS_PASSWORD env var"
    elif irods_a.exists():
        # mesa-mcp builds an iRODSAccount directly, so it needs the secret
        # rather than the obfuscated .irodsA. Prompt, but say why.
        import getpass

        print("note: .irodsA exists, but mesa-mcp builds an account directly")
        password = getpass.getpass(f"iRODS password for {args.user} (not echoed): ")
        source = "interactive prompt"
    else:
        import getpass

        password = getpass.getpass(f"iRODS password for {args.user} (not echoed): ")
        source = "interactive prompt"

    print(f"credential source: {source}")
    print(f"target: {host}:{port} zone={zone}\n")

    cfg = Config(irods=IRODSConfig(host=host, port=port, zone=zone, user=args.user))
    current_config.set(cfg)
    current_client_pool.set(IRODSClientPool(host=host, port=port))

    user_auth = AuthValue(
        username=args.user, zone=zone, password=password, auth_scheme="native"
    )
    anon_auth = AuthValue(
        username=ANONYMOUS_USER, zone=zone, password=None, auth_scheme="anonymous"
    )

    async def listing(path: str, auth: AuthValue) -> tuple[bool, str]:
        token = current_auth_value.set(auth)
        try:
            out = await handle_list_directory(ListDirectoryInput(path=path))
            # The tool returns ``directory_entries`` plus a ``total``.
            n = out.get("total", len(out.get("directory_entries") or []))
            return True, f"{n} entries"
        except Exception as exc:
            return False, _describe(exc)
        finally:
            current_auth_value.reset(token)

    # --- 1. public, unauthenticated -------------------------------------
    if args.public:
        ok, why = await listing(args.public, anon_auth)
        RESULT["1_public_unauthenticated"] = "ok -- " + why if ok else f"FAILED: {why}"
    else:
        RESULT["1_public_unauthenticated"] = (
            "skipped -- pass --public <a genuinely public collection>"
        )

    # --- 2. private, as the authenticated user --------------------------
    home = f"/{zone}/home/{args.user}"
    ok, why = await listing(home, user_auth)
    RESULT["2_private_as_user"] = f"ok -- {why}" if ok else f"FAILED: {why}"

    # A private path must NOT be readable anonymously. Without this the
    # scenario-2 pass says nothing about privacy.
    ok_anon, why_anon = await listing(home, anon_auth)
    RESULT["2b_private_denied_to_anonymous"] = (
        f"LEAK -- anonymous read the private home ({why_anon})"
        if ok_anon
        else f"correctly refused ({why_anon})"
    )

    # --- 3. shared ------------------------------------------------------
    if args.shared:
        ok, why = await listing(args.shared, user_auth)
        RESULT["3_shared_as_user"] = f"ok -- {why}" if ok else f"FAILED: {why}"
    else:
        RESULT["3_shared_as_user"] = "skipped -- pass --shared <collection>"

    # --- 4. write to an owned collection --------------------------------
    scratch = f"{home}/mesa_mcp_probe_{uuid.uuid4().hex[:8]}"
    target = f"{scratch}/hello.txt"
    token = current_auth_value.set(user_auth)
    try:
        try:
            await handle_make_directory(MakeDirectoryInput(path=scratch))
            RESULT["4a_make_directory"] = "ok"
        except Exception as exc:
            RESULT["4a_make_directory"] = f"FAILED: {_describe(exc)}"
            raise

        payload = "mesa-mcp write probe\n"
        try:
            await handle_write_file(WriteFileInput(path=target, content=payload))
            RESULT["4b_write_file"] = "ok"
        except Exception as exc:
            RESULT["4b_write_file"] = f"FAILED: {_describe(exc)}"
            raise

        try:
            out = await handle_read_file(ReadFileInput(path=target))
            # Text files come back under ``text``; a mismatch here would
            # mean the write and read disagree, which is worth catching.
            got = out.get("text")
            RESULT["4c_read_back"] = (
                "ok -- content matches"
                if got == payload
                else f"MISMATCH -- wrote {payload!r}, read {got!r}"
            )
        except Exception as exc:
            RESULT["4c_read_back"] = f"FAILED: {_describe(exc)}"
    except Exception:
        pass  # verdicts already recorded
    finally:
        # Always clean up the scratch collection.
        try:
            from mesa_mcp.irods.tools.delete_file import (
                DeleteFileInput,
                handle_delete_file,
            )

            # ds_delete_file removes a collection recursively by default.
            await handle_delete_file(DeleteFileInput(path=scratch))
            RESULT["4d_cleanup"] = "ok"
        except Exception as exc:
            RESULT["4d_cleanup"] = f"MANUAL CLEANUP NEEDED at {scratch}: {_describe(exc)}"
        current_auth_value.reset(token)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="End-to-end ds_* access scenarios (no secrets printed)."
    )
    ap.add_argument("--user", required=True)
    ap.add_argument("--public", default=None, help="a genuinely public collection")
    ap.add_argument("--shared", default=None, help="a shared collection you can read")
    args = ap.parse_args()

    try:
        asyncio.run(_run(args))
    except Exception as exc:  # pragma: no cover - top-level safety
        RESULT["fatal"] = _describe(exc)

    print("---------- report back this block (no secrets) ----------")
    for key, value in RESULT.items():
        print(f"{key}: {value}")
    print("--------------------------------------------------------")
    return 0


if __name__ == "__main__":
    sys.exit(main())
