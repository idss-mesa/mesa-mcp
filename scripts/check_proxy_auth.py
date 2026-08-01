#!/usr/bin/env python3
"""Probe whether iRODS proxy auth is usable for the mesa-mcp OIDC path.

Run this **on a machine that can reach the zone** (port 1247). It answers
the operational question blocking the OIDC -> iRODS identity fix:

    Can <admin> authenticate and then act as another user via proxy auth,
    with the zone's ACLs still applied to the *proxied* user?

Credentials
-----------
Nothing is typed, logged, or stored by this script. It uses the standard
iRODS credential chain, in order:

1. ``~/.irods/irods_environment.json`` + ``~/.irods/.irodsA`` -- i.e. the
   result of ``iinit``. **This is the recommended path**: the password is
   already on your machine, obfuscated, and never passes through a shell
   or an argument list.
2. ``MESA_MCP_IRODS_PASSWORD`` if you must override.
3. An interactive ``getpass`` prompt as a last resort -- not echoed, and
   not written to shell history.

Do not pass a password as a command-line argument: argv is visible to
other processes via ``ps``.

Usage
-----
    python scripts/check_proxy_auth.py --admin tswetnam --as-user someuser

The printed report contains no secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe iRODS proxy auth (no secrets printed).")
    ap.add_argument("--admin", required=True, help="rodsadmin username (e.g. tswetnam)")
    ap.add_argument(
        "--as-user",
        required=True,
        help="username to act as; a real non-admin account you can verify",
    )
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--zone", default=None)
    args = ap.parse_args()

    env = _load_env_file()
    host = args.host or env.get("irods_host") or "data.cyverse.org"
    port = args.port or int(env.get("irods_port") or 1247)
    zone = args.zone or env.get("irods_zone_name") or "iplant"

    try:
        from irods.session import iRODSSession
    except ImportError:
        print("python-irodsclient is not installed: pip install python-irodsclient")
        return 2

    irods_a = Path(
        os.environ.get(
            "IRODS_AUTHENTICATION_FILE", Path.home() / ".irods" / ".irodsA"
        )
    )
    password: str | None = None
    if irods_a.exists():
        source = "~/.irods/.irodsA (iinit)"
    elif os.environ.get("MESA_MCP_IRODS_PASSWORD"):
        password = os.environ["MESA_MCP_IRODS_PASSWORD"]
        source = "MESA_MCP_IRODS_PASSWORD env var"
    else:
        import getpass

        password = getpass.getpass(f"iRODS password for {args.admin} (not echoed): ")
        source = "interactive prompt"

    print(f"credential source: {source}")
    print(f"target: {host}:{port} zone={zone}")
    print(f"admin: {args.admin} | acting as: {args.as_user}\n")

    def session(**kw):
        if password is None:
            return iRODSSession(irods_env_file=str(_env_file_path()), **kw)
        return iRODSSession(
            host=host, port=port, zone=zone, user=args.admin, password=password, **kw
        )

    # 1. Plain admin login, and confirm the account really is rodsadmin.
    try:
        with session() as s:
            RESULT["admin_login"] = "ok"
            RESULT["server_version"] = str(s.server_version)
            me = s.users.get(args.admin)
            RESULT["admin_user_type"] = me.type
            RESULT["admin_is_rodsadmin"] = me.type == "rodsadmin"
    except Exception as exc:
        RESULT["admin_login"] = f"FAILED: {type(exc).__name__}: {exc}"
        _report()
        return 1

    # 2. Proxy auth: admin authenticates, acts as another user.
    try:
        with session(client_user=args.as_user, client_zone=zone) as s:
            coll = s.collections.get(f"/{zone}/home/{args.as_user}")
            RESULT["proxy_auth"] = "ok"
            RESULT["proxy_saw_home"] = coll.path
            RESULT["proxy_entries"] = len(coll.data_objects) + len(coll.subcollections)
    except Exception as exc:
        RESULT["proxy_auth"] = f"FAILED: {type(exc).__name__}: {exc}"

    # 3. The security question: are ACLs applied to the PROXIED user, or
    #    does the admin's reach leak through? Reading a third party's home
    #    while acting as a non-admin must fail.
    other = args.admin if args.as_user != args.admin else "rods"
    try:
        with session(client_user=args.as_user, client_zone=zone) as s:
            s.collections.get(f"/{zone}/home/{other}")
        RESULT["acl_enforced_on_proxied_user"] = (
            f"NO -- as {args.as_user} we could read /{zone}/home/{other}"
        )
    except Exception as exc:
        RESULT["acl_enforced_on_proxied_user"] = f"yes ({type(exc).__name__})"

    _report()
    return 0


def _report() -> None:
    print("---------- report back this block (no secrets) ----------")
    for key, value in RESULT.items():
        print(f"{key}: {value}")
    print("--------------------------------------------------------")


if __name__ == "__main__":
    sys.exit(main())
