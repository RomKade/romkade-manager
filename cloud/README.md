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
  `game_details`, `library_overview`, `get_cheats`, `console_status`, `launch_game`, `quit_game`, `save_state`,
  `set_volume`). Chacun renvoie une vue (`view`) de l'interface ROMKADE.
- `romkade_cloud/ui/app.html` : interface ROMKADE dans ChatGPT, Claude… (extension **MCP Apps**, ressource
  `ui://romkade/app.html`). Même charte que le Manager : grille de jaquettes, fiche du jeu, carte « En cours sur la
  console » (volume, sauvegarder, quitter), bibliothèque par console, cheats, consoles. Boutons reliés aux outils
  (`tools/call`), thème clair ou sombre et langue (fr, en, es) de l'assistant.
- `art.py` : jaquettes (`/art/<clé>.webp`, libretro-thumbnails comme le Manager, mises en cache sur le serveur).
  `static/` : polices (OFL), illustrations des consoles (retroarch-assets, CC BY 4.0), logo.
- `relay.py` : file d'ordres par console, long polling, résultats.
- `catalog.py` : tri et enrichissement de la liste de fichiers envoyée par l'agent, avec les règles et les bases du
  Manager : vrai titre des jeux d'arcade, genre, année, développeur, éditeur, résumé. La liste brute est gardée et
  recalculée au démarrage quand `catalog.VERSION` change. Les cheats viennent de la base libretro.
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

Sur la console : menu **APPS → ROMKADE**. L'écran ROMKADE (`screen.py`, Pillow écrit dans `/dev/fb0` comme l'app
Horloge du firmware) montre le code d'appairage en grand, puis « Console connectée » et le nombre de jeux. L'app démarre l'agent, l'ajoute au démarrage de la console (une ligne
marquée `# ROMKADE` dans `/mnt/mod/ctrl/autostart`, retirée par `romkade/uninstall.sh`) et affiche le code
d'appairage à donner à l'assistant : « Connecte ma console, code ABC123 ».

Essayé sur RG35XX Pro (firmware Anbernic + Stock OS Mod) : détection, état, volume et inventaire (5 696
fichiers) depuis l'agent. Les autres firmwares suivent les profils du Manager, sans essai.

## Déploiement (droplet)

En ligne sur **https://www.likyly.com/romkade/** (connecteur : `https://www.likyly.com/romkade/mcp/<jeton>`).

- `deploy/Dockerfile`, `deploy/compose.yaml` : conteneur `romkade-cloud`, sans port publié, sur le réseau
  `licenses_web` du Caddy commun de la droplet ; données (base, cheats, jaquettes) dans le volume
  `deploy_romkade_data`.
- `deploy/deploy.sh` : envoie les sources (hôte SSH `do-deployer`, dossier `~/app/romkade-cloud`) et reconstruit.
- `deploy/caddy.snippet` : route ajoutée au bloc `www.likyly.com` du Caddyfile commun
  (`~/app/licenses/caddy/Caddyfile`, image `caddy-edge`) ; le préfixe `/romkade` est retiré avant le serveur.
  Le Caddyfile sert aussi d'autres sites (xp-flightdeck, licences, datatoform…) : sauvegarde, `caddy validate`,
  puis `caddy reload` à chaud. Le disque système de la droplet est presque plein ; Docker est sur
  `/mnt/volume_add_1`.

Pas de sous-domaine pour l'instant (romkade.com est sur l'hébergement mutualisé OVH du site). Un domaine à nous
(`mcp.romkade.com` ou autre) sera nécessaire pour les annuaires ChatGPT et Claude.

## Licence

Propriétaire : © 2026 ROMKADE, tous droits réservés ([LICENSE](../LICENSE), composants tiers dans [NOTICE](../NOTICE)).
La mention figure aussi dans l'interface MCP Apps et sur l'écran de la console.
