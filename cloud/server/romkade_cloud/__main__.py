"""python -m romkade_cloud serve [--port 8787]
python -m romkade_cloud new-account [libellé]          compte à jeton (prototype), affiche l'adresse du connecteur
python -m romkade_cloud accounts                        comptes, avec leur nombre de consoles
python -m romkade_cloud move-consoles <de> <vers>       rattache les consoles d'un compte à un autre
python -m romkade_cloud demo-console <e-mail ou id>     console de démonstration du compte (relecteurs, demo.py)"""

import argparse
import logging
import os

from .store import Store


def main() -> None:
    p = argparse.ArgumentParser(prog="romkade_cloud")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)
    a = sub.add_parser("new-account", help="crée un compte et affiche l'adresse de son connecteur MCP")
    a.add_argument("label", nargs="?")
    sub.add_parser("accounts", help="liste les comptes")
    m = sub.add_parser("move-consoles", help="rattache les consoles d'un compte à un autre")
    m.add_argument("source")
    m.add_argument("target")
    d = sub.add_parser("demo-console", help="rattache une console de démonstration à un compte")
    d.add_argument("account", help="adresse e-mail du compte ou identifiant (sb:…)")
    args = p.parse_args()

    if args.cmd == "demo-console":
        from .demo import find_account, setup

        store = Store(os.environ.get("ROMKADE_CLOUD_DB", "data/cloud.sqlite3"))
        account = find_account(store, args.account)
        if account is None:
            raise SystemExit(f"compte {args.account} introuvable : se connecter une fois à ROMKADE avec ce compte")
        c = setup(store, account)
        print(f"console de démo {c.id} ({c.label}) rattachée à {account} ; en ligne d'ici une minute")
        return

    if args.cmd in ("accounts", "move-consoles"):
        store = Store(os.environ.get("ROMKADE_CLOUD_DB", "data/cloud.sqlite3"))
        if args.cmd == "accounts":
            for a in store.accounts():
                print(f"{a['id']}\t{a['label'] or ''}\t{a['consoles']} console(s)")
        else:
            print(f"{store.move_consoles(args.source, args.target)} console(s) rattachée(s) à {args.target}")
        return

    if args.cmd == "new-account":
        _, token = Store(os.environ.get("ROMKADE_CLOUD_DB", "data/cloud.sqlite3")).create_account(args.label)
        base = os.environ.get("ROMKADE_PUBLIC_URL", "http://127.0.0.1:8787").rstrip("/")
        print(f"{base}/{token}")
        return

    import uvicorn

    from .app import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    uvicorn.run(create_app(), host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")


main()
