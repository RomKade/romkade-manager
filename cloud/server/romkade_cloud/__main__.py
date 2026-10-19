"""python -m romkade_cloud serve [--port 8787]  |  python -m romkade_cloud new-account [libellé]"""

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
    args = p.parse_args()

    if args.cmd == "new-account":
        _, token = Store(os.environ.get("ROMKADE_CLOUD_DB", "data/cloud.sqlite3")).create_account(args.label)
        base = os.environ.get("ROMKADE_PUBLIC_URL", "http://127.0.0.1:8787").rstrip("/")
        print(f"{base}/mcp/{token}")
        return

    import uvicorn

    from .app import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    uvicorn.run(create_app(), host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")


main()
