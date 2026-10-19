# ROMKADE Cloud (prototype)

Piloter sa console et discuter avec son catalogue depuis ChatGPT, Claude… par un serveur MCP hébergé, **sans le
Manager sur l'ordinateur**.

```
ChatGPT / Claude / …  ──MCP (HTTPS)──▶  serveur cloud  ◀──HTTPS sortant (long polling)──  agent sur la console
```

La console n'est pas joignable depuis Internet : c'est son **agent** qui appelle le cloud et vient chercher les
ordres. Rien à ouvrir sur la box, pas d'IP, pas de SSH.

## Serveur (`server/`)

- `romkade_cloud/tools.py` : outils MCP (`pair_console`, `list_consoles`, `rename_console`, `search_games`,
  `library_overview`, `get_cheats`, `console_status`, `launch_game`, `quit_game`, `save_state`, `set_volume`).
- `relay.py` : file d'ordres par console, long polling, résultats.
- `catalog.py` : tri de la liste de fichiers envoyée par l'agent (règles du Manager : `app.platforms`,
  `app.services.classify`). Les cheats viennent de la base libretro (`app.services.cheats`).
- `store.py` : comptes, consoles, catalogues (SQLite ; secrets gardés en empreinte SHA-256).

```sh
cd cloud/server
python3.13 -m venv .venv && .venv/bin/pip install -e . -e ../../backend pytest
.venv/bin/python -m pytest -q tests
ROMKADE_PUBLIC_URL=https://… .venv/bin/python -m romkade_cloud new-account "Moi"   # adresse du connecteur
ROMKADE_PUBLIC_URL=https://… .venv/bin/python -m romkade_cloud serve --port 8787
```

Prototype : le jeton dans l'adresse `/mcp/<jeton>` tient lieu de connexion. À remplacer par OAuth (comptes
ROMKADE) avant toute ouverture au public : c'est aussi ce qu'exigent les annuaires d'apps ChatGPT et Claude.

## Agent (`agent/`)

Python 3.10+ de la console, bibliothèque standard seule. Il embarque les modules de pilotage du Manager
(`launcher`, `volume`, `systems`), qui s'exécutent sur place au lieu de passer par SSH. Il n'accepte que des
actions nommées (`status`, `launch`, `quit`, `save_state`, `volume`, `rescan`), jamais de commande libre.

```sh
cd cloud/agent && ./build.sh https://adresse-du-cloud   # -> dist/sd, à copier à la racine de la carte SD
```

Sur la console : menu **APPS → ROMKADE**. L'app démarre l'agent, l'ajoute au démarrage de la console (une ligne
marquée `# ROMKADE` dans `/mnt/mod/ctrl/autostart`, retirée par `romkade/uninstall.sh`) et affiche le code
d'appairage à donner à l'assistant : « Connecte ma console, code ABC123 ».

Essayé sur RG35XX Pro (firmware Anbernic + Stock OS Mod) : détection, état, volume et inventaire (5 696
fichiers) depuis l'agent. Les autres firmwares suivent les profils du Manager, sans essai.
