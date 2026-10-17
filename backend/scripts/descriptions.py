"""Descriptions des jeux en français, anglais et espagnol, par Claude (app/services/descriptions.py).

Usage (depuis backend/) :
    .venv/bin/python scripts/descriptions.py essai 3      # 3 jeux tout de suite, sans lot, résultats affichés (non enregistrés)
    .venv/bin/python scripts/descriptions.py lancer       # soumet le lot de tous les jeux sans description complète
    .venv/bin/python scripts/descriptions.py suivre       # état des lots ; importe ceux qui sont terminés

Identifiants Anthropic : la clé enregistrée dans Paramètres > Descriptions (trousseau macOS), sinon ceux du SDK
(ANTHROPIC_API_KEY, ou le profil de ~/.config/anthropic). Le coût est facturé sur le compte Anthropic correspondant.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import data_dir  # noqa: E402
from app.credentials import KeyringStore  # noqa: E402
from app.db.session import init_db  # noqa: E402
from app.services import descriptions as d  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("essai", "lancer", "suivre"):
        print(__doc__)
        return 1
    sessions = init_db(data_dir() / "catalog.sqlite3")
    client = d.make_client(KeyringStore())
    cmd = sys.argv[1]
    if cmd == "essai":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        with sessions() as s:
            games = d.pending_games(s, limit=None)
        # un jeu avec résumé, puis des jeux sans : les deux cas
        sample = [g for g in games if g["summary"]][:1] + [g for g in games if not g["summary"]][: n - 1]
        for game in sample:
            mode, params = d.params_for(game)
            message = client.messages.create(**params)
            data = d.parse(message)
            print(f"\n=== {game['title']} ({game['platform']}) · {mode} · {message.usage.input_tokens} + "
                  f"{message.usage.output_tokens} jetons")
            print(json.dumps(data, ensure_ascii=False, indent=1) if data else f"(rien : {message.stop_reason})")
        return 0
    if cmd == "lancer":
        with sessions() as s:
            out = d.submit(s, client)
        print(f"Lot {out['batch_id']} : {out['games']} jeux" if out["batch_id"] else "Tous les jeux ont déjà leurs descriptions.")
        return 0
    for entry in d.load_state():
        batch = client.messages.batches.retrieve(entry["batch_id"])
        c = batch.request_counts
        print(f"{entry['batch_id']} · {batch.processing_status} · {c.succeeded} réussis, {c.errored} erreurs, "
              f"{c.processing} en cours · {'importé' if entry.get('imported') else 'à importer'}")
        if batch.processing_status == "ended" and not entry.get("imported"):
            with sessions.begin() as s:
                print("  importé :", d.import_results(s, client, entry["batch_id"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
