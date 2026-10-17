"""Configuration initiale + synchronisation du catalogue + rapport, sans passer par l'API.

Usage (depuis backend/) :
    .venv/bin/python scripts/catalog_report.py                    # réglages enregistrés
    .venv/bin/python scripts/catalog_report.py --host 192.168.86.242

Au premier lancement : confirme l'empreinte de la clé d'hôte, demande le mot de passe et le range
dans le trousseau macOS, enregistre les réglages. Les lancements suivants ne demandent rien.
Le scan est en lecture seule. Le catalogue écrit est le même que celui de l'API.
"""

import argparse
import asyncio
import getpass
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DeviceSettings, SettingsStore, data_dir  # noqa: E402
from app.credentials import KeyringStore  # noqa: E402
from app.db.session import init_db  # noqa: E402
from app.device.ssh_client import DeviceClient, HostKeyStore, fetch_host_key, fingerprint  # noqa: E402
from app.errors import AppError  # noqa: E402
from app.services import catalog_query as cq  # noqa: E402
from app.services.catalog_sync import _create_run, _finish_run, run_sync  # noqa: E402


def gb(n: int | None) -> str:
    return f"{(n or 0) / 1e9:.2f} Go"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--samples", type=int, default=5, help="Exemples d'images non rapprochées par plateforme")
    a = ap.parse_args()

    store = SettingsStore()
    settings = store.load()
    if a.host or a.port:
        settings = DeviceSettings(**{**settings.model_dump(), **({"host": a.host} if a.host else {}),
                                     **({"port": a.port} if a.port else {})})
    store.save(settings)
    print(f"Console : {settings.username}@{settings.host}:{settings.port}  racine {settings.roms_root}")
    print(f"Données : {data_dir()}")

    host_keys = HostKeyStore(data_dir() / "known_hosts")
    if not host_keys.has_entry(settings.host, settings.port):
        key = await fetch_host_key(settings)
        print(f"Clé d'hôte inconnue : {key.get_algorithm()} {fingerprint(key)}")
        if input("Faire confiance à cette clé ? [o/N] ").strip().lower() != "o":
            return 1
        host_keys.trust(settings.host, settings.port, key)

    creds = KeyringStore()
    if not creds.get_password(settings.host, settings.username):
        creds.set_password(settings.host, settings.username,
                           getpass.getpass(f"Mot de passe {settings.username}@{settings.host} (rangé dans le trousseau) : "))

    sessions = init_db(data_dir() / "catalog.sqlite3")
    run_id = _create_run(sessions, settings)
    t0 = time.perf_counter()
    print("Synchronisation en cours (lecture seule)...")
    try:
        await run_sync(sessions, DeviceClient(settings, creds, host_keys), run_id)
    except AppError as exc:
        _finish_run(sessions, run_id, "failed", f"{exc.code}: {exc.message}")
        print(f"ÉCHEC {exc.code} : {exc.message} {exc.details or ''}")
        return 2

    with sessions() as s:
        run = cq.get_run(s, run_id)
        st = cq.status(s, False)
        plats = cq.list_platforms(s)
        dups = cq.duplicates(s, None)
        unmatched = cq.unmatched_images(s, a.samples)

    print(f"\nStatut : {run.status} en {time.perf_counter() - t0:.1f} s")
    print(f"Changements : +{run.added} ajoutés, ~{run.modified} modifiés, -{run.removed} disparus, {run.restored} revenus")
    for d, err in run.platform_errors.items():
        print(f"  Erreur sur {d} : {err}")
    print(f"Catalogue : {st.game_count} jeux candidats, {st.file_count} fichiers, {gb(st.total_bytes)}")
    print(f"Carte : {gb(st.storage_free_bytes)} libres / {gb(st.storage_total_bytes)}")
    print(f"Images : {run.images_matched} rapprochées sur {run.images_seen}")

    print(f"\n{'Dossier':<11} {'Plateforme':<26} {'Jeux':>5} {'Fich.':>6} {'Img':>6} {'Rapp.':>6}")
    for p in plats:
        if p.file_count or p.image_count:
            print(f"{p.directory:<11} {(p.label or '?')[:26]:<26} {p.game_count:>5} {p.file_count:>6} "
                  f"{p.image_count:>6} {p.images_matched:>6}")

    print(f"\nDoublons potentiels : {len(dups)} groupes "
          f"({sum(1 for d in dups if d.confidence == 'likely')} probables)")
    for d in dups[:10]:
        print(f"  [{d.confidence}] {d.platform.directory} : " + " | ".join(i.filename for i in d.items))

    print("\nImages non rapprochées (exemples, pour affiner la règle de correspondance) :")
    for u in unmatched:
        print(f"  {u.platform.directory} ({u.total}) : " + " | ".join(u.sample))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
