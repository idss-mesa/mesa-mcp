#!/usr/bin/env python3
"""Probe what a *non-admin* iRODS account can do for mesa-mcp.

Proxy auth needs rodsadmin, which we are not pursuing. This probes the
alternative: an ordinary ``rodsuser`` who **owns collections** issuing
scoped, revocable iRODS **tickets**. Tickets are the one delegation
mechanism in iRODS that does not require elevated privilege.

The questions, in order of how much they constrain the design:

1. What can this account actually reach and write under the nominated
   collection?
2. Can it issue a ticket for a collection it owns?
3. Does that ticket work from a **separate session** — i.e. is it a real
   delegation, not just a local no-op?
4. Do the restrictions **bind**? ``user`` (single-user scoping) and
   ``uses`` (spend limit) decide whether a ticket can stand in for
   per-caller identity.

   Each is tested by *observing behaviour change*, not by whether the
   server accepted the ``modify`` call — applying a restriction proves
   only that it was accepted. So the probe pins the ticket and then
   re-tries the anonymous session, and sets ``uses=1`` and then uses the
   ticket twice.
5. Can it be revoked?

Check order is load-bearing: delegation (3) is measured on an
**unrestricted** ticket, *before* any restriction is applied. Applying a
user restriction first would make a correctly-binding restriction look
like a broken delegation.

Safety
------
* Creates a **read-only** ticket on the collection you nominate, and
  revokes it in a ``finally``. Nothing is written to iRODS data.
* **Ticket strings are never printed.** A ticket is a bearer capability —
  anyone holding the string has the access it grants. The report shows
  only whether operations succeeded.
* Credentials come from the standard chain (``.irodsA`` from ``iinit``,
  then ``MESA_MCP_IRODS_PASSWORD``, then ``getpass``). No ``--password``
  flag: argv is visible via ``ps``.

Usage
-----
    python3 scripts/check_user_capabilities.py \\
        --user tswetnam --collection /iplant/home/shared/<a-collection-you-own>

Report back the printed block; it contains no secrets.
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
    ap = argparse.ArgumentParser(
        description="Probe non-admin iRODS capabilities (no secrets printed)."
    )
    ap.add_argument("--user", required=True, help="your iRODS username")
    ap.add_argument(
        "--collection",
        required=True,
        help="a collection you OWN (e.g. /iplant/home/shared/yourproject)",
    )
    ap.add_argument(
        "--other-user",
        default=None,
        help=(
            "optional second account to test the ticket's user-restriction "
            "against; omit to skip that check"
        ),
    )
    args = ap.parse_args()

    env = _load_env_file()
    host = env.get("irods_host") or "data.cyverse.org"
    port = int(env.get("irods_port") or 1247)
    zone = env.get("irods_zone_name") or "iplant"

    try:
        from irods.session import iRODSSession
        from irods.ticket import Ticket
    except ImportError:
        print("python-irodsclient is not installed: pip install python-irodsclient")
        return 2

    irods_a = Path(
        os.environ.get("IRODS_AUTHENTICATION_FILE", Path.home() / ".irods" / ".irodsA")
    )
    password: str | None = None
    if irods_a.exists():
        source = "~/.irods/.irodsA (iinit)"
    elif os.environ.get("MESA_MCP_IRODS_PASSWORD"):
        password = os.environ["MESA_MCP_IRODS_PASSWORD"]
        source = "MESA_MCP_IRODS_PASSWORD env var"
    else:
        import getpass

        password = getpass.getpass(f"iRODS password for {args.user} (not echoed): ")
        source = "interactive prompt"

    print(f"credential source: {source}")
    print(f"target: {host}:{port} zone={zone}")
    print(f"user: {args.user} | collection: {args.collection}\n")

    def session(**kw):
        if password is None:
            return iRODSSession(irods_env_file=str(_env_file_path()), **kw)
        return iRODSSession(
            host=host, port=port, zone=zone, user=args.user, password=password, **kw
        )

    def anon_session():
        """A session with no credentials — the ticket must carry the access."""
        return iRODSSession(host=host, port=port, zone=zone, user="anonymous", password="")

    # --- 1. What can this account reach? --------------------------------
    try:
        with session() as s:
            coll = s.collections.get(args.collection)
            RESULT["collection_readable"] = "ok"
            RESULT["entries"] = len(coll.data_objects) + len(coll.subcollections)
            acl = s.acls.get(coll)
            mine = [
                a.access_name
                for a in acl
                if getattr(a, "user_name", None) == args.user
            ]
            RESULT["my_access_on_collection"] = mine or "none listed (may be via group)"
            RESULT["i_own_it"] = any("own" in a for a in mine)
    except Exception as exc:
        RESULT["collection_readable"] = f"FAILED: {type(exc).__name__}: {exc}"
        _report()
        return 1

    # --- 1b. NEGATIVE CONTROL -------------------------------------------
    #
    # Everything below infers "the ticket granted access" from an anonymous
    # session succeeding. That inference is only valid if the anonymous
    # user CANNOT already read the collection. /<zone>/home/shared is
    # world-readable on CyVerse, so without this control every ticket
    # result is uninterpretable: the ticket is not necessarily what opened
    # the door, and a *binding* restriction would still look like "NO".
    try:
        with anon_session() as anon:
            anon.collections.get(args.collection)
        RESULT["anon_reads_without_ticket"] = (
            "YES -- collection is already anonymous-readable; ticket checks "
            "below cannot attribute access to the ticket"
        )
        anon_baseline = True
    except Exception as exc:
        RESULT["anon_reads_without_ticket"] = f"no ({type(exc).__name__}) -- good control"
        anon_baseline = False

    # --- 2..5 ticket lifecycle ------------------------------------------
    ticket_string: str | None = None
    try:
        with session() as s:
            try:
                t = Ticket(s)
                t.issue("read", args.collection)
                ticket_string = t._ticket  # never printed
                RESULT["can_issue_ticket"] = "ok"
            except Exception as exc:
                RESULT["can_issue_ticket"] = f"FAILED: {type(exc).__name__}: {exc}"
                _report()
                return 1

        # ORDERING MATTERS. Delegation is measured on an UNRESTRICTED
        # ticket first; restrictions are applied only afterwards, so a
        # binding restriction cannot be misread as "delegation broken".

        def _open_with_ticket() -> tuple[bool, str]:
            """Try to read the collection from an anonymous ticket session."""
            try:
                with anon_session() as anon:
                    Ticket(anon, ticket=ticket_string).supply()
                    c = anon.collections.get(args.collection)
                    return True, f"{len(c.data_objects) + len(c.subcollections)} entries"
            except Exception as exc:
                return False, f"{type(exc).__name__}"

        # 3. Does the ticket delegate to a SEPARATE session? The real test:
        #    an anonymous session holding only the ticket.
        opened, detail = _open_with_ticket()
        if anon_baseline:
            RESULT["ticket_works_in_separate_session"] = (
                "INCONCLUSIVE -- anonymous could already read this collection "
                "without a ticket (see anon_reads_without_ticket); re-run "
                "against a collection OUTSIDE /home/shared"
            )
        else:
            RESULT["ticket_works_in_separate_session"] = (
                "ok" if opened else f"FAILED: {detail}"
            )
            if opened:
                RESULT["ticket_saw"] = detail

        # 3b. Does the ticket LEAK beyond its collection?
        try:
            with anon_session() as anon:
                Ticket(anon, ticket=ticket_string).supply()
                anon.collections.get(f"/{zone}/home/{args.user}")
            RESULT["ticket_scope_contained"] = (
                f"NO -- ticket also opened /{zone}/home/{args.user}"
            )
        except Exception as exc:
            RESULT["ticket_scope_contained"] = f"yes ({type(exc).__name__})"

        # 4. Do restrictions BIND? Applying a restriction only proves the
        #    server accepted the modify call. Each check below therefore
        #    applies the restriction and then RE-EXERCISES the ticket to
        #    observe whether behaviour actually changed.
        if anon_baseline:
            # A restriction could bind perfectly and the anonymous session
            # would STILL open the collection -- via its own standing
            # access, not the ticket. Reporting "NO" here would be a false
            # negative that condemns a working mechanism.
            RESULT["restriction_user_binds"] = (
                "INCONCLUSIVE -- anonymous has standing read on this "
                "collection, so continued access proves nothing about the "
                "restriction"
            )
            RESULT["restriction_uses_binds"] = "INCONCLUSIVE -- same"
        elif not opened:
            RESULT["restriction_user_binds"] = (
                "INCONCLUSIVE -- ticket did not delegate, nothing to restrict"
            )
            RESULT["restriction_uses_binds"] = "INCONCLUSIVE -- same"
        else:
            # 4a. Per-user restriction. THE decisive check for per-caller
            #     identity: after pinning the ticket to another user, an
            #     anonymous session must NO LONGER be able to use it.
            if args.other_user:
                try:
                    with session() as s:
                        Ticket(s, ticket=ticket_string).modify(
                            "add", "user", args.other_user
                        )
                    still_open, why = _open_with_ticket()
                    if still_open:
                        RESULT["restriction_user_binds"] = (
                            f"NO -- accepted, but an anonymous session STILL "
                            f"opened the collection after pinning to "
                            f"{args.other_user}"
                        )
                    else:
                        RESULT["restriction_user_binds"] = f"yes -- now refused ({why})"
                except Exception as exc:
                    RESULT["restriction_user_binds"] = (
                        f"not applicable -- modify rejected: {type(exc).__name__}"
                    )
            else:
                RESULT["restriction_user_binds"] = (
                    "skipped (pass --other-user to test the decisive check)"
                )

            # 4b. Spend limit. Set uses to 1 and use it twice: the second
            #     attempt must fail. Only run when the ticket is still
            #     usable — a bound user-restriction above already closed it.
            usable, _ = _open_with_ticket()
            if not usable:
                RESULT["restriction_uses_binds"] = (
                    "INCONCLUSIVE -- ticket already closed by the user "
                    "restriction above"
                )
            else:
                try:
                    with session() as s:
                        Ticket(s, ticket=ticket_string).modify("uses", "1")
                    first, _ = _open_with_ticket()
                    second, why2 = _open_with_ticket()
                    if first and not second:
                        RESULT["restriction_uses_binds"] = f"yes -- spent ({why2})"
                    elif first and second:
                        RESULT["restriction_uses_binds"] = (
                            "NO -- accepted, but the ticket worked twice with uses=1"
                        )
                    else:
                        RESULT["restriction_uses_binds"] = (
                            "INCONCLUSIVE -- ticket stopped working before the "
                            "limit could be observed"
                        )
                except Exception as exc:
                    RESULT["restriction_uses_binds"] = (
                        f"not applicable -- modify rejected: {type(exc).__name__}"
                    )

    finally:
        # 5. Always revoke, even if a check above raised.
        if ticket_string:
            try:
                with session() as s:
                    Ticket(s, ticket=ticket_string).delete()
                RESULT["ticket_revoked"] = "ok"
            except Exception as exc:
                RESULT["ticket_revoked"] = (
                    f"FAILED -- REVOKE MANUALLY: {type(exc).__name__}: {exc}"
                )

    _report()
    return 0


def _report() -> None:
    print("---------- report back this block (no secrets) ----------")
    for key, value in RESULT.items():
        print(f"{key}: {value}")
    print("--------------------------------------------------------")


if __name__ == "__main__":
    sys.exit(main())
