"""Diagnostic en lecture seule de la vraie console.

Usage (depuis backend/) :
    .venv/bin/python scripts/diagnose_device.py --host 192.168.86.242

Le mot de passe est demandé au clavier (non affiché, non enregistré).
Ce script n'écrit RIEN sur la console. Il vérifie :
  1. la clé d'hôte (empreinte à comparer),
  2. l'authentification,
  3. la disponibilité de SFTP,
  4. l'extension statvfs et la commande df,
  5. l'arborescence de la racine des ROMs et les extensions observées.
"""

import argparse
import asyncio
import collections
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncssh  # noqa: E402

from app.device.remote_fs import ReadOnlyRemoteFS  # noqa: E402
from app.services.inventory import scan_all  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.86.242")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--user", default="root")
    ap.add_argument("--root", default="/mnt/mmc/Roms")
    a = ap.parse_args()

    print(f"[1] Clé d'hôte de {a.host}:{a.port}")
    key = await asyncssh.get_server_host_key(a.host, a.port)
    print(f"    {key.get_algorithm()}  {key.get_fingerprint('sha256')}")
    print("    Compare avec : ssh-keygen -lf <(ssh-keyscan -p", a.port, a.host, "2>/dev/null)")
    if input("    Cette empreinte est-elle la bonne ? [o/N] ").strip().lower() != "o":
        return 1

    password = getpass.getpass(f"[2] Mot de passe {a.user}@{a.host} : ")
    async with asyncssh.connect(a.host, port=a.port, username=a.user, password=password,
                                client_keys=None, agent_path=None, known_hosts=None) as conn:
        # known_hosts=None uniquement ici, après confirmation manuelle de l'empreinte ci-dessus.
        if conn.get_server_host_key().get_fingerprint("sha256") != key.get_fingerprint("sha256"):
            print("    ERREUR : clé différente de celle confirmée"); return 1
        print("    Authentification OK")
        info = await conn.run("uname -a; cat /etc/os-release 2>/dev/null | head -3; "
                              "ls -l /usr/lib/openssh/sftp-server /usr/libexec/sftp-server /usr/lib/sftp-server 2>/dev/null; "
                              "ps | grep -E 'sshd|dropbear' | grep -v grep | head -3", check=False)
        print("    Système :\n      " + "\n      ".join(str(info.stdout).splitlines()))

        print("[3] SFTP")
        try:
            sftp = await conn.start_sftp_client()
        except Exception as exc:  # noqa: BLE001
            print(f"    INDISPONIBLE : {type(exc).__name__}: {exc}"); return 2
        print(f"    OK (version {sftp.version})")

        fs = ReadOnlyRemoteFS(conn, sftp, a.root)
        print(f"[4] Racine {a.root} existe : {await fs.root_exists()}")
        try:
            v = await sftp.statvfs(a.root)
            print(f"    statvfs OK : total={v.blocks * (v.frsize or v.bsize)} libre={v.bavail * (v.frsize or v.bsize)}")
        except Exception as exc:  # noqa: BLE001
            print(f"    statvfs indisponible ({type(exc).__name__}), repli df")
        st = await fs.storage()
        print(f"    Espace ({st.method}) : {st.free_bytes / 1e9:.2f} Go libres / {st.total_bytes / 1e9:.2f} Go")

        print("[5] Inventaire")
        inv = await scan_all(fs, include_files=True)
        print(f"    {inv.platform_count} dossiers, {inv.file_count} fichiers, "
              f"{inv.candidate_count} candidats, {inv.total_bytes / 1e9:.2f} Go, {inv.duration_ms:.0f} ms")
        for p in inv.platforms:
            if not p.file_count and not p.image_count:
                continue
            exts = collections.Counter(f.extension for f in p.files or [])
            print(f"    {p.directory:<11} {p.file_count:>5} fichiers  img={p.image_count:<5} "
                  f"{dict(exts.most_common(6))}" + (f"  ignorés={len(p.skipped)}" if p.skipped else ""))
        sftp.exit()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
