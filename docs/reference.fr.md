<p align="center">
  <a href="https://romkade.com"><img src="../frontend/src/assets/brand/romkade-manager-logo-480.webp" alt="ROMKADE Manager" width="360"></a>
</p>

<p align="center"><strong>🌐 <a href="https://romkade.com">romkade.com</a></strong> · <a href="https://romkade.com/docs/fr/">Documentation</a> · <a href="https://github.com/RomKade/romkade-manager/releases/latest">Dernière version</a></p>

<p align="center"><a href="reference.md">English</a> · <strong>Français</strong> · <a href="reference.es.md">Español</a></p>

# ROMKADE Manager — référence technique

Gère et pilote tes consoles rétro portables (Anbernic, Miyoo, TrimUI…) depuis le navigateur de ton ordinateur, sous
macOS, Windows ou Linux : bibliothèque, ajout de jeux, lancement sur la console, sauvegardes, temps de jeu, manettes,
Bluetooth. **La console n'est modifiée que par des actions que tu lances : ajout de jeux, restauration ou suppression
d'une sauvegarde, réglages Bluetooth et manettes des joueurs.**

Guide d'utilisation : **[romkade.com/docs](https://romkade.com/docs/fr/)**. Architecture, modèle de données et choix
techniques : [docs/ARCHITECTURE.md](ARCHITECTURE.md).

## Sommaire

- **Installation** :
  - [Installer avec Docker (macOS, Windows, Linux)](#installer-avec-docker-macos-windows-linux) — [Mettre à jour, sauvegarder, désinstaller](#mettre-à-jour-sauvegarder-désinstaller) · [Clé SSH et IA locale avec Docker](#clé-ssh-et-ia-locale-avec-docker) · [Publier une version](#publier-une-version)
  - [Lancer depuis le code source (macOS)](#lancer-depuis-le-code-source-macos)
- **Développement** : [1. Diagnostic de la vraie console (recommandé d'abord)](#1-diagnostic-de-la-vraie-console-recommandé-dabord) · [2. Synchroniser le catalogue (phase 2)](#2-synchroniser-le-catalogue-phase-2) · [3. Lancer l'application](#3-lancer-lapplication) · [Modifier l'interface (Node 20 ou plus : brew install node)](#modifier-linterface-node-20-ou-plus--brew-install-node) · [4. Premier branchement via l'API (inutile si catalog_report.py a été lancé)](#4-premier-branchement-via-lapi-inutile-si-catalog_reportpy-a-été-lancé) · [5. Utilisation](#5-utilisation)
- **Fonctions** : [Ajouter des jeux](#ajouter-des-jeux) · [Genres](#genres) · [Illustrations des consoles](#illustrations-des-consoles) · [Bandes-annonces](#bandes-annonces) · [Jaquettes](#jaquettes) · [Jouer sur la console depuis l'interface](#jouer-sur-la-console-depuis-linterface) · [Langues](#langues) · [Sauvegardes](#sauvegardes) · [Reprendre une partie depuis une sauvegarde](#reprendre-une-partie-depuis-une-sauvegarde) · [Bluetooth](#bluetooth) · [Manettes](#manettes) · [Volume](#volume) · [Depuis le téléphone (ngrok)](#depuis-le-téléphone-ngrok) · [Informations sur les jeux](#informations-sur-les-jeux) · [Commandes des jeux](#commandes-des-jeux) · [Connexion à une IA (LLM)](#connexion-à-une-ia-llm) · [Assistant de jeu](#assistant-de-jeu) · [Favoris](#favoris) · [Temps de jeu](#temps-de-jeu) · [Tableau de bord](#tableau-de-bord)
- **Fonctionnement** : [Garanties](#garanties) · [Recherche (Typesense)](#recherche-typesense) · [Connexion à la console](#connexion-à-la-console) · [Autres consoles et systèmes](#autres-consoles-et-systèmes)
- **Projet** : [Version, conditions d'utilisation](#version-conditions-dutilisation) · [Sources et crédits](#sources-et-crédits)

## Installer avec Docker (macOS, Windows, Linux)

L'installation recommandée, identique sur les trois systèmes, sur processeurs Intel/AMD et ARM (Apple Silicon,
Raspberry Pi).

1. Installe Docker : [Docker Desktop](https://docs.docker.com/desktop/) sur macOS et Windows, ou
   [Docker Engine](https://docs.docker.com/engine/install/) avec le plugin Compose sur Linux.
2. Télécharge le fichier `compose.yaml` de la dernière version et démarre ROMKADE Manager :

   macOS et Linux :

   ```bash
   mkdir romkade && cd romkade
   curl -fsSLO https://github.com/RomKade/romkade-manager/releases/latest/download/compose.yaml
   docker compose up -d
   ```

   Windows (PowerShell) :

   ```powershell
   mkdir romkade; cd romkade
   curl.exe -fsSLO https://github.com/RomKade/romkade-manager/releases/latest/download/compose.yaml
   docker compose up -d
   ```

3. Ouvre http://localhost:8765, puis **Paramètres > Connexion** : adresse IP de la console, utilisateur SSH et mot de
   passe, approbation de la clé de la console, test de connexion, puis synchronisation.

Image : `ghcr.io/romkade/romkade-manager` (`latest`, ou une version comme `0.4.0`). La recherche (Typesense) est un
second service du même fichier, sans port publié. L'interface n'écoute que sur cet ordinateur (`127.0.0.1`) : ne
l'expose pas sur Internet, elle pilote ta console. Le conteneur joint la console sur le réseau local en SSH :
ordinateur et console sur le même réseau.

### Mettre à jour, sauvegarder, désinstaller

Dans le dossier `romkade` :

| Action | Commande |
|---|---|
| Mettre à jour | `docker compose pull && docker compose up -d` |
| Journaux | `docker compose logs -f` |
| Arrêter | `docker compose down` (données conservées) |
| Sauvegarder les données | `docker run --rm -v romkade_romkade-data:/data -v "$PWD":/backup alpine tar czf /backup/romkade-data.tgz -C /data .` |
| Tout supprimer | `docker compose down`, puis `docker volume rm romkade_romkade-data romkade_typesense-data` |

Le volume `romkade-data` garde le catalogue, les réglages, les copies de sauvegardes et les secrets (`secrets.json`,
lisible par le seul compte du conteneur). Jamais `docker compose down -v` par habitude : cela supprime les volumes.

Options, dans un fichier `.env` à côté de `compose.yaml` : `ROMKADE_PORT` (défaut `8765`), `ROMKADE_VERSION` (défaut
`latest`), `TZ` (défaut `Europe/Paris`).

### Clé SSH et IA locale avec Docker

- **Clé SSH** au lieu d'un mot de passe : le conteneur ne voit que son volume. Copie la clé dedans une fois, puis
  indique `/data/id_ed25519` comme chemin de la clé privée :

  ```bash
  docker compose exec -T romkade sh -c 'cat > /data/id_ed25519 && chmod 600 /data/id_ed25519' < ~/.ssh/id_ed25519
  ```

- **IA locale** (Ollama, LM Studio) sur cet ordinateur : adresse `http://host.docker.internal:11434/v1` dans
  Paramètres > Assistant. Guide : [docs/local-llm.fr.md](local-llm.fr.md).

### Publier une version

Même numéro dans `backend/pyproject.toml` et `frontend/package.json`, puis `git tag vX.Y.Z && git push origin vX.Y.Z`.
Le workflow [Image Docker](../.github/workflows/docker.yml) publie l'image (`X.Y.Z`, `X.Y`, `latest`, amd64 + arm64) et
une release GitHub avec `compose.yaml`. Chaque push sur `main` publie `edge`.
La variable du dépôt `POSTHOG_KEY` (clé publique `phc_…`) active dans l'image les statistiques anonymes sur accord.

## Lancer depuis le code source (macOS)

Pour le développement, ou pour utiliser l'application [depuis le téléphone](#depuis-le-téléphone-ngrok). Il faut le
Python 3.13 officiel de [python.org](https://www.python.org/downloads/macos/) (le Python de Homebrew est bloqué par
l'autorisation « Réseau local » de macOS et renvoie « No route to host »), et Node 20 ou plus (`brew install node`)
pour compiler l'interface.

```bash
git clone https://github.com/RomKade/romkade-manager.git
cd romkade-manager
./run.sh
```

Au premier lancement, le script prépare l'environnement Python et compile l'interface (`frontend/dist`), puis démarre
le serveur et ouvre http://127.0.0.1:8765 dans le navigateur. `Ctrl+C` arrête le serveur. Mots de passe et clés vont
dans le trousseau du système ; les données dans `~/Library/Application Support/AnbernicGameManager`
(`ROMKADE_DATA_DIR` pour en changer ; sous Windows `%APPDATA%\AnbernicGameManager`, sous Linux
`~/.local/share/AnbernicGameManager`).

Installation manuelle et tests :

```bash
cd romkade-manager/backend
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q               # tests contre un serveur SFTP simulé
```

## 1. Diagnostic de la vraie console (recommandé d'abord)

```bash
.venv/bin/python scripts/diagnose_device.py --host 192.168.86.242
```

Le script affiche l'empreinte de la clé d'hôte, demande le mot de passe (non enregistré), puis vérifie SFTP, l'espace disque et l'arborescence. Il n'écrit rien sur la console.

Pour comparer l'empreinte indépendamment :

```bash
ssh-keyscan -p 22 192.168.86.242 2>/dev/null | ssh-keygen -lf -
```

## 2. Synchroniser le catalogue (phase 2)

```bash
.venv/bin/python scripts/catalog_report.py
```

Au premier lancement : confirmation de la clé d'hôte, mot de passe rangé dans le trousseau, réglages
enregistrés. Ensuite, aucune question. Le script scanne la carte en lecture seule, met à jour
`~/Library/Application Support/AnbernicGameManager/catalog.sqlite3` et affiche un rapport
(jeux par plateforme, changements, doublons, images non rapprochées).

## 3. Lancer l'application

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Interface : http://127.0.0.1:8765. Documentation de l'API : http://127.0.0.1:8765/docs

## Modifier l'interface (Node 20 ou plus : `brew install node`)

```bash
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173, relaie /api vers le backend lancé sur 8765
npm test             # tests Vitest
npm run build        # recompile frontend/dist, servi ensuite par le backend
npm run gen:api      # régénère les types TypeScript depuis l'OpenAPI (backend lancé)
```

## 4. Premier branchement via l'API (inutile si catalog_report.py a été lancé)

```bash
API=http://127.0.0.1:8765/api

# Réglages (non sensibles, stockés dans ~/Library/Application Support/AnbernicGameManager/)
curl -s -X PUT $API/settings -H 'Content-Type: application/json' \
  -d '{"host":"192.168.86.242","port":22,"username":"root","auth_method":"password","roms_root":"/mnt/mmc/Roms"}'

# Mot de passe -> trousseau macOS (jamais renvoyé par l'API). read -s évite l'historique du shell.
read -s PW && curl -s -X PUT $API/settings/password -H 'Content-Type: application/json' \
  -d "{\"password\":\"$PW\"}"; unset PW

# Clé d'hôte : afficher, vérifier, puis confirmer en recopiant l'empreinte
curl -s $API/device/host-key
curl -s -X POST $API/device/host-key/trust -H 'Content-Type: application/json' \
  -d '{"fingerprint":"SHA256:...."}'
```

## 5. Utilisation

Catalogue (servi depuis SQLite, console éteinte comprise) :

```bash
curl -s -X POST $API/catalog/sync                       # lance une synchronisation (202 + id)
curl -s $API/catalog/sync/1                             # avancement : platforms_done / platforms_total
curl -s $API/catalog/status | python3 -m json.tool      # totaux, dernière synchro, espace carte
curl -s $API/platforms
curl -s "$API/games?q=mario&platform=SFC&sort=name&limit=20"
curl -s "$API/games?region=Europe&extension=chd&has_image=true"
curl -s $API/games/42                                   # fiche + doublons + historique
open  http://127.0.0.1:8765/api/games/42/image          # image Imgs (mise en cache locale)
curl -s $API/catalog/changes                            # ajouts / modifs / disparitions de la dernière synchro
curl -s $API/catalog/duplicates
curl -s $API/catalog/unmatched-images
```

Accès direct à la console (diagnostic) :

```bash
curl -s -X POST $API/device/test-connection | python3 -m json.tool
curl -s $API/device/storage
curl -s "$API/device/inventory?include_files=true&platform=PS"
```

## Ajouter des jeux

Page **Ajouter des jeux** (anciennement « Transferts », `/ajouter-des-jeux`) : glisse des fichiers ou clique sur « Choisir des fichiers ».

1. Les fichiers sont d'abord copiés dans une zone d'attente sur le Mac (`~/Library/Application Support/AnbernicGameManager/staging`), avec calcul de leur empreinte SHA-256.
2. Pour chacun, l'application propose la console de destination d'après le format et signale : nom refusé par la carte, format inhabituel, fichier déjà présent (casse comprise), titre déjà présent, espace insuffisant (marge de 256 Mo minimum).
3. « Copier sur la console » : chaque fichier est écrit sous un nom temporaire caché, vérifié (empreinte SHA-256 calculée sur la console, sinon la taille), puis renommé. Le catalogue des consoles concernées est ensuite relu.
4. Un fichier déjà présent n'est jamais remplacé sans confirmation. En cas de remplacement, l'ancien est déplacé dans `/mnt/mmc/Roms/.agm-backups/<console>/` (même carte, aucun espace consommé). Tu peux supprimer ce dossier à la main quand tu n'en as plus besoin.
5. Annulation ou coupure : le fichier temporaire est supprimé, rien n'apparaît sur la carte. Un transfert échoué ou annulé peut être relancé tant que le fichier est en zone d'attente.

## Garanties

- Lecture et écriture séparées : `ReadOnlyRemoteFS` pour tout ce qui lit, `RemoteWriter` pour les seules copies. L'écriture est limitée aux dossiers de consoles existants (jamais APPS, PORTS, un lien symbolique ou un fichier système), et la seule suppression possible concerne les fichiers temporaires de l'application.
- Le serveur refuse les requêtes venues d'autres sites ouverts dans le navigateur (contrôle des en-têtes Origin et Host).
- Clé d'hôte vérifiée, confirmation explicite au premier contact, blocage si elle change.
- Mot de passe dans le trousseau macOS uniquement.
- Chemins validés et confinés sous la racine, liens symboliques signalés et jamais suivis.
- Dossiers `Imgs` comptés à part, jamais comme des jeux. Un fichier `candidate` n'est pas affirmé jouable.
- Synchronisation : un fichier disparu est marqué `deleted_at`, jamais effacé ; une plateforme en erreur garde ses fichiers ; racine absente ou vide : synchronisation refusée sans rien modifier.
- Rôles : `candidate` (jeu potentiel), `component` (piste .bin d'un .cue, disque d'un .m3u), `auxiliary` (texte, sauvegarde), `program` (APPS, PORTS).
- Serveur lié à 127.0.0.1.

## Genres

La bibliothèque filtre par genre (Sport, Tir, Plateforme…). Les genres viennent d'une table embarquée,
`backend/app/data/genres.json.gz`, rapprochée par nom de fichier : libretro-database pour les consoles
(noms No-Intro), catver.ini (progettoSNAPS) pour l'arcade (noms courts MAME). Aucun accès réseau à l'usage ;
les genres sont recalculés à chaque démarrage et après chaque synchronisation.
Seconde source : [OpenVGDB](https://github.com/OpenVGDB/OpenVGDB) (base d'OpenEmu), indispensable pour les
consoles à CD (PlayStation, Saturn, Mega-CD, PC Engine CD) absentes de libretro. Les noms de fichiers
approximatifs sont rapprochés par titre compact (« Bomberman2 »), préfixe retiré (« SS-Clockwork Knight »),
début de titre (nom tronqué), puis par le même jeu sur une autre console ou en arcade. Pour rafraîchir la table :

```bash
cd backend && .venv/bin/python scripts/build_genres.py
```

Les jeux d'arcade affichent leur titre complet (« sf2.zip » → « Street Fighter II: The World Warrior »),
tiré des listes MAME, FBNeo et HBMAME de libretro-database, dans la même table.

## Illustrations des consoles

`frontend/public/consoles/*.webp` : thème XMB « systematic » de
[retroarch-assets](https://github.com/libretro/retroarch-assets) (CC-BY 4.0). Pour en ajouter :
`cd backend && .venv/bin/python scripts/build_console_icons.py`, puis recompiler l'interface.

## Bandes-annonces

Le bouton ▶ d'une jaquette cherche une vidéo avec l'API officielle YouTube Data v3. Il faut une clé d'API
gratuite (Paramètres → Bandes-annonces YouTube), rangée dans le trousseau macOS. Une recherche coûte
100 unités sur un quota de 10 000 par jour, soit environ 100 jeux par jour : la recherche se fait au premier
clic, puis le résultat (les 5 vidéos les plus pertinentes) est gardé en cache dans le catalogue. Sans clé,
le bouton ouvre la recherche sur youtube.com.

## Jaquettes

Les images du dossier `Imgs` de la carte sont souvent des montages pour le menu de la console. La grille
affiche plutôt la vraie boîte du jeu, tirée de [libretro-thumbnails](https://thumbnails.libretro.com)
(la banque d'images de RetroArch), par nom No-Intro ou, pour l'arcade, par titre complet. Si le nom exact
manque, le titre le plus proche est cherché dans la liste des fichiers de la banque. Chaque jaquette est
téléchargée au premier affichage puis gardée dans `cache/boxart` sur le Mac ; rien n'est écrit sur la
carte. Le sélecteur « Jaquettes / Images de la carte » de la bibliothèque permet de revenir aux images
de la carte.

## Jouer sur la console depuis l'interface

Dans la fiche d'un jeu, « Jouer sur la console » ferme le menu (ou le jeu RetroArch en cours, avec sa
sauvegarde automatique) et lance le jeu sur la console ; le menu revient quand on quitte le jeu.
L'encart de la console, dans la barre latérale, affiche le jeu en cours et propose « Quitter le jeu ».

Fonctionne avec le firmware Anbernic muni du « Stock OS Mod » (`/mnt/mod/ctrl/RA_launch.sh`, cœurs de
`/mnt/mod/ctrl/configs/CORES.txt`). Le script `backend/app/device/launch.sh` est envoyé par SSH et exécuté
détaché : il met en pause la boucle du menu (`/mnt/vendor/ctrl/loadapp.sh`), ferme `dmenu.bin` proprement
(SIGINT), remet l'écran dans son mode de démarrage (640×480, 32 bits, enregistré par le mod dans
`configs/fb.cfg` ; sans cela RetroArch ne peut pas s'afficher), lance le jeu comme le fait le mod, puis
relâche la boucle à la sortie du jeu. « Quitter le jeu » envoie la commande réseau `QUIT` de RetroArch
(UDP 55355). Aucun fichier n'est écrit sur la carte ;
le journal est dans `/tmp/agm-launch.log` sur la console.

## Langues

L'interface existe en français, anglais et espagnol (sélecteur en bas de la barre latérale, choix gardé
dans le navigateur). Textes : `frontend/src/i18n/locales/*.ts`, un fichier par zone, les trois langues
côte à côte. Le serveur répond en français ; l'interface traduit ses erreurs à partir de leur code.

## Sauvegardes

Page « Sauvegardes » : toutes les sauvegardes de la carte, rattachées à leur jeu, lues en lecture seule
dans les dossiers du firmware (sous `/mnt/mmc`) :

| Dossier | Contenu |
|---|---|
| `saves_RA/Roms/<CONSOLE>/<cœur>/` | sauvegardes « en jeu » RetroArch (`.srm`, `.save.zip`, `.nvmem`) |
| `states_RA/Roms/<CONSOLE>/<cœur>/` | instantanées RetroArch (`.state`, `.stateN`, `.state.auto`) |
| `save/Roms/<CONSOLE>/` | émulateurs d'origine d'Anbernic (`.stN`, `.mds.gz`, `.srm`) |
| `save_nds/` | DraStic (Nintendo DS) |
| `.config/ppsspp/PSP/SAVEDATA/` | PPSSPP (PSP), un dossier par identifiant de jeu |
| `Roms/<CONSOLE>/*.sav` | sauvegardes posées à côté du jeu |

- « Copier toutes les sauvegardes sur le Mac » crée un dossier daté dans
  `~/Library/Application Support/AnbernicGameManager/save-backups/`, téléchargeable en `.zip`.
- Restaurer un fichier d'une copie, ou supprimer une sauvegarde de la carte : refusé pendant qu'un jeu tourne,
  et toujours précédé d'une copie automatique sur le Mac du fichier remplacé ou supprimé. Les écritures passent
  par `app/device/save_writer.py`, limité aux emplacements de sauvegarde.
- Le guide « Comment sauvegarder » affiche les raccourcis RetroArch réellement configurés sur la console.
- Tableau de bord : « Sauvegarder maintenant » envoie la commande réseau `SAVE_STATE` de RetroArch au jeu en cours.

## Reprendre une partie depuis une sauvegarde

Sur la page Sauvegardes et dans la fiche d'un jeu, chaque sauvegarde a un bouton :
- « Reprendre ici » (instantanée RetroArch) : lance le jeu sur la console puis charge cet emplacement dès que
  RetroArch fait tourner le jeu (commandes réseau `GET_STATUS` puis `LOAD_STATE_SLOT n`) ; l'instantanée
  « auto » passe par l'option `auto` de `RA_launch.sh` ;
- « Jouer » (sauvegarde en jeu) : lance le jeu, qui charge lui-même sa sauvegarde.

## Bluetooth

Page « Bluetooth » : état du Bluetooth de la console, appareils appairés et à portée (recherche de 12 s),
appairer / connecter / déconnecter / oublier, et « Son des jeux ici » pour une enceinte ou un casque.

- La console a BlueZ et BlueALSA, mais rien ne démarre `bluealsa` : sans lui une enceinte s'appaire sans
  recevoir de son. L'application le lance à la demande (`bluealsa -p a2dp-source`, processus détaché).
- « Son des jeux ici » : RetroArch est un programme 32 bits, le greffon ALSA de BlueALSA n'existe qu'en 64 bits,
  et RetroArch ouvre toujours la sortie ALSA « default ». L'application installe donc
  `/etc/alsa/conf.d/60-agm-bluetooth.conf` (sortie `agm_bt` : le son est passé à `aplay`, 64 bits, vers
  l'enceinte ; si elle est absente, il est absorbé et le jeu continue sans son) et `/.asoundrc`
  (`pcm.!default agm_bt`, lu par les jeux lancés depuis Game Manager, qui tournent avec `HOME=/`).
  Le relais recopie aussi le son vers la sortie HDMI (muette sans câble) : elle donne à RetroArch une horloge
  temps réel ; sans elle (sortie « null »), le son arrivait haché.
  « Remettre le son sur la console » supprime ces deux fichiers. Le menu de la console, et les jeux lancés
  depuis lui, gardent ses haut-parleurs.
- Manettes récentes (Xbox, 8BitDo…) : elles sont en Bluetooth basse consommation et ne s'appairent que pendant
  une recherche active. La connexion se fait donc en une seule session `bluetoothctl` (agent, `scan on`, `pair`,
  `trust`, `connect`), journal dans `/tmp/agm-bt-connect.log` sur la console. Si l'appareil est appairé mais ne
  répond pas, il faut le réveiller (bouton Xbox / Home) puis cliquer de nouveau sur « Connecter ».
- Le firmware efface les appairages à chaque démarrage (`/mnt/vendor/ctrl/loadapp.sh` vide
  `/var/lib/bluetooth`), et `bluealsa` n'est pas relancé : après un redémarrage, reconnecter l'appareil depuis
  cette page.

## Manettes

Page « Manettes » : qui contrôle le jeu. Manette de chaque joueur dans RetroArch (`input_playerN_joypad_index`,
numéros du pilote sdl2 : 0 = boutons de la console, puis manettes USB / Bluetooth dans l'ordre de branchement).
RetroArch enregistre sa config en quittant : un joueur 1 resté sur une ancienne manette absente empêche la console
de contrôler le jeu (« Utiliser les boutons de la console » la remet sur le joueur 1). Le choix est rangé dans
`/.config/agm-players`, écrit tout de suite dans `/.config/retroarch/retroarch.cfg` si aucun jeu ne tourne, sinon
par `launch.sh` au prochain jeu lancé depuis Game Manager (une fois RetroArch fermé). Choisir une manette pour un
joueur l'échange avec le joueur qui l'avait.

RetroArch (pilote sdl2 avec udev) ne numérote pas les manettes dans l'ordre de `/proc/bus/input/devices` mais
par chemin sysfs : avec une manette Xbox USB, `…/soc/5101000.ohci0…` passe avant les boutons
`…/soc/soc@03000000:gpio_keys` (Xbox = 0, console = 1), et « joueur 1 = manette n°1 » donnait la main à la
console. `/.config/agm-players` garde les numéros de Game Manager ; `players_apply.sh` (lancé par Game Manager
sans jeu en cours, et par `launch.sh` avant chaque jeu, avec les manettes branchées à ce moment) les traduit dans
l'ordre de RetroArch et réserve en plus la manette au joueur (`input_playerN_reserved_device = "045e:0b12 Generic
X-Box pad"`, type 1 = préférée). Ce qui a été appliqué est copié dans `/.config/agm-players.applied` ; le
résultat est noté dans `/tmp/agm-launch.log` (« joueurs pour RetroArch : 0 045e:0b12 Generic X-Box pad 1 … »).

Avec une manette branchée en plus des boutons de la console, « Jouer sur la console » (fiche du jeu) demande
d'abord « Qui joue ? » : le choix devient le joueur 1, puis le jeu est lancé.

Le bouton de l'en-tête suit la situation : un changement en attente pendant un jeu RetroArch connu de la
bibliothèque donne « Relancer le jeu pour appliquer » ; un joueur 1 sur une manette absente donne « Utiliser les
boutons de la console » (puis la bibliothèque sans jeu en cours, ou la relance du jeu en cours) ; sinon, sans jeu
en cours, « Choisir un jeu » ouvre la bibliothèque. La relance repasse par `launch.sh` : le jeu est quitté
proprement avec sa sauvegarde automatique, les manettes sont écrites, puis il reprend en `auto` si le système sait
reprendre.

## Volume

Dans le bloc « En cours » du tableau de bord, dans le bandeau « En cours » de la fiche du jeu et dans la barre du
haut quand un jeu tourne : couper / remettre le
son et curseur de volume (1 à 100 % = -40 à 0 dB), valable pour les haut-parleurs comme pour une enceinte
Bluetooth.

Ce qui ne marche pas sur cette console, d'où ce choix :
- le mixeur de la puce son : pendant un jeu, ses réglages sont verrouillés (`amixer` ne change rien, sans erreur) ;
- les commandes réseau `VOLUME_UP` / `VOLUME_DOWN` de RetroArch : ignorées (seule `MUTE` marche).

Game Manager ajoute donc son propre volume logiciel ALSA : `/.asoundrc` (lu par les jeux lancés depuis Game
Manager, `HOME=/`) fait passer la sortie « default » par deux `softvol` (volume « Game Manager », puis coupure),
avant les haut-parleurs ou la sortie Bluetooth `agm_bt`. Le réglage « Game Manager » est créé sur la carte 0 avant
le premier jeu après un démarrage, par une seconde de silence jouée avec `aplay` (mis alors à 60 %) : créé par
RetroArch, il restait verrouillé par lui tout ce jeu (curseur et touches Vol+/Vol- sans effet). Il se règle ensuite
avec `amixer`, même en plein jeu. Au
lancement, `launch.sh` met le volume propre de RetroArch (`audio_volume`, souvent très bas) à 0 dB.
Un jeu lancé depuis le menu de la console n'utilise pas `/.asoundrc` : seule la coupure marche (`MUTE`).

## Depuis le téléphone (ngrok)

**À la maison, même Wi-Fi** : le bouton téléphone, en haut de l'interface, affiche un QR code. Scanne-le avec
l'appareil photo du téléphone : le Manager s'ouvre sur le téléphone, sans se reconnecter au compte (c'est
l'ordinateur, connecté, qui l'a associé). Le code vaut 5 minutes et ne sert qu'une fois ; le téléphone reste ensuite
associé 90 jours. Tant qu'un téléphone est associé, le serveur écoute aussi sur l'adresse de l'ordinateur dans le
réseau local, mais ne répond qu'aux téléphones associés ; « Déconnecter », dans la même fenêtre, les dissocie tous
et ferme cet accès. Pas encore avec Docker. Sur macOS, la première fois, autorise les connexions entrantes pour
Python si la question est posée.

**Hors de la maison**, avec ngrok :

```bash
./run.sh --telephone
```

Publie l'interface sur une adresse https ngrok (compte ngrok configuré une fois : `ngrok config add-authtoken …`)
et affiche l'adresse, l'identifiant, le mot de passe et un QR code. L'application n'a pas de comptes : ngrok
demande l'identifiant et le mot de passe **avant** que la requête n'arrive sur le Mac (règle `basic-auth`,
`phone_policy.yml` dans le dossier de données). Le mot de passe est créé au premier lancement
(`phone_password`, lisible par toi seul) et gardé ensuite. Le serveur n'accepte, en plus de localhost, que
l'adresse ngrok de ce lancement (`AGM_EXTRA_HOSTS`). `Ctrl+C` arrête le serveur et l'accès. Sans `--telephone`,
rien n'est publié.

## Informations sur les jeux

Fiche du jeu : genre (pictogramme), régions (drapeaux), sortie, éditeur, développeur, franchise (liens
Wikipédia dans la langue de l'interface), résumé (en anglais) et fiche GameFAQs. Table embarquée
`backend/app/data/gameinfo.json.gz`, construite par `scripts/build_gameinfo.py` (libretro-database, OpenVGDB,
listes arcade MAME / FBNeo / HBMAME), rapprochée par nom de fichier comme les genres. La recherche trouve aussi
l'année, l'éditeur, le développeur, la franchise, et les régions et genres en français, anglais et espagnol
(« Japon », « Japan », « Japón »).

## Commandes des jeux

Section « Commandes » de la fiche : quelle touche de la console fait quoi dans ce jeu (« B : coup de poing »,
« A : tir »), avec quelques astuces. « Demander à Claude » fait un appel (Opus 5.5, effort moyen, quelques
centimes) avec la correspondance par défaut des cœurs RetroArch entre la manette d'origine et les touches de la
console (Mega Drive : A = Y, B = B, C = A ; PlayStation : Croix = B, Rond = A… ; arcade : bouton 1 = B, 2 = A…,
pièce = Select). Réponse en français, anglais et espagnol, gardée en base (table `game_controls`, partagée par
les éditions d'un même jeu). Jeu mal connu du modèle : commandes habituelles de la console, signalé comme tel.
« Corriger » / « Saisir à la main » remplace la liste par la sienne (même texte dans les trois langues). Même clé
d'API IA que les descriptions (Paramètres > Assistant).

## Connexion à une IA (LLM)

Paramètres > Assistant : l'IA de l'[assistant de jeu](#assistant-de-jeu), qui sert aussi, à la demande, aux
descriptions et aux commandes des jeux, avec un voyant d'état
(gris : aucune, orange : vérification, vert : connectée, rouge : erreur). `backend/app/services/llm.py` :

| Choix | Clé | Remarques |
|---|---|---|
| Claude (Anthropic) | `sk-ant-…` | Claude Opus 5.5 par défaut ; descriptions en lot (moitié prix) |
| ChatGPT (OpenAI), Mistral, Gemini | clé du fournisseur | protocole OpenAI (chat completions) |
| Modèle local ou service compatible OpenAI | facultative | Ollama, LM Studio (Mac, Windows, Linux) ou toute adresse `…/v1` ; gratuit et hors ligne en local |

- Service en ligne : le choisir et coller la clé, rien d'autre. Le modèle est pris dans la liste du fournisseur
  (`suggest_model`, jamais un nom inventé) et reste modifiable ; la connexion est vérifiée toute seule (une toute
  petite demande réelle) et le résultat allume le voyant (`last_test` dans `llm.json`).
- Aucune IA par défaut (une clé Anthropic déjà enregistrée garde Claude, comme avant).
- Clés dans le trousseau du système (ou `secrets.json` dans Docker), une par fournisseur, avec un œil pour les
  afficher ; à défaut la variable d'environnement du fournisseur (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `MISTRAL_API_KEY`, `GEMINI_API_KEY`).
- Modèle local : adresses prêtes Ollama, LM Studio et Ollama (Docker) (`host.docker.internal`, déclaré dans
  `compose.yaml` pour Linux). Guide pas à pas : [docs/local-llm.fr.md](local-llm.fr.md).
- Réponses en JSON : sorties structurées (`json_schema`), sinon JSON simple avec le schéma dans la consigne
  (modèles locaux qui ne les gèrent pas).
- Descriptions sans Claude : jeu par jeu en arrière-plan (arrêt après 5 échecs d'affilée, reprise possible).

## Assistant de jeu

Une bulle en bas à droite de toutes les pages : un assistant IA pour **ta bibliothèque** (trouver un jeu, en
comparer deux, se servir de l'application). Sur la fiche d'un jeu, ou pendant qu'un jeu tourne sur la console, il
propose de discuter de **ce jeu** seulement (commandes, objectifs, passage difficile, secrets : un indice d'abord, la
solution sur demande). Il utilise l'IA réglée dans Paramètres > Assistant, en ligne ou locale (Ollama, LM Studio ; on demande
aux modèles à raisonnement de répondre sans réflexion préalable, ce qui garde un modèle local de 12B autour de 10 s par
réponse). Chaque question passe par deux appels : un aiguillage structuré (dans le sujet ou non, intention, genre,
console), puis la réponse en flux, construite à partir de la fiche du jeu et des passages de **connaissances**. Les
questions hors sujet, les demandes de ROM ou de BIOS et les tentatives de changer ses consignes reçoivent le refus de
l'application, jamais le texte du modèle. Les conversations restent dans le navigateur.

**Connaissances** (Paramètres > Connaissances, sans IA) : pour chaque jeu, ses pages Wikipédia (en, fr, es) et sa soluce
StrategyWiki, récupérées sans IA par les API MediaWiki une fois le jeu identifié par Wikidata (jeu vidéo + bonne
console), découpées en passages avec leur source et leur licence (CC BY-SA 4.0, citée dans les réponses), indexées
dans Typesense. Récupération pour un jeu (test, avec une question de test qui montre les passages trouvés) ou pour
tous ; option de récupération automatique des nouveaux jeux après chaque synchronisation. Conception :
[docs/STRATEGIE-IA.md](STRATEGIE-IA.md).

## Favoris

« Ajouter aux favoris » sur la fiche d'un jeu (l'édition ouverte). Les favoris apparaissent dans « Mes favoris » du
tableau de bord (le dernier ajouté en premier, avec « Rejouer ») et dans la bibliothèque : bouton « Favoris » des
filtres, ou `/bibliotheque?fav=1` (lien « Tous mes favoris »). Rangés dans la base du Mac (table `favorite`).

Les favoris appartiennent à une console : chacun garde l'empreinte SHA-256 de la clé SSH approuvée de la console
(stable, contrairement à son adresse IP). Brancher une autre console (celle d'un ami, un autre firmware) n'affiche que
ses propres favoris, limités aux jeux présents sur sa carte ; les autres restent en base et reviennent avec leur console.

## Temps de jeu

Page « Temps de jeu » : temps du jour, des 7 derniers jours et total, histogramme sur 14 jours, temps par jeu,
dernières parties ; carte « Aujourd'hui » sur le tableau de bord.

- **Suivi par Game Manager** (`app/services/playtime.py`) : tant que le serveur tourne, il regarde toutes les
  30 s ce qui tourne sur la console et enregistre des sessions datées avec l'horloge du Mac (table
  `play_session`). C'est ce qui donne l'historique et le temps par jour. `AGM_NO_TRACKER=1` le désactive.
- **Journaux de RetroArch** (`/mnt/vendor/deep/retro/playlists/logs/<cœur>/<jeu>.lrtl`) : temps total par jeu,
  y compris les parties lancées depuis le menu de la console. Les totaux par jeu prennent le plus grand des deux.
- **Alerte** (Paramètres → Temps de jeu) : au bout de N heures de la partie en cours ou de la journée, avec
  rappel facultatif. Elle s'affiche en pop-in dans Game Manager et, si coché, sur l'écran de la console pendant
  le jeu (commande réseau `SHOW_MSG` de RetroArch). Réglages dans `play_settings.json` du dossier de données.


Filtre « Du … au … » : jours, jeux et parties de cette période. Seules les parties suivies par Game Manager y
comptent : les journaux de RetroArch (`.lrtl`) ne donnent qu'un total par jeu, sans dates.

Effacer : la corbeille d'un jeu (dans « Par jeu ») ou « Tout effacer », avec confirmation. Les parties de Game
Manager sont supprimées ; rien n'est modifié sur la console : le total des journaux RetroArch du jeu au moment de
l'effacement est retenu (table `play_reset`) et retiré ensuite, si bien que seul le temps joué depuis compte. La
partie en cours, si elle est concernée, repart de zéro.
## Tableau de bord

Dans l'ordre : le jeu en cours, les jeux joués récemment (bouton ▶ pour les relancer sur la console ;
historique RetroArch de la console complété par les parties suivies par Game Manager, `GET /api/play/recent`),
les derniers ajouts avec un lien « Ajouter des jeux », la carte microSD, puis les consoles les plus fournies et
l'activité (dernière partie, temps de jeu du jour, synchronisation, jeux en cours d'ajout).

## Recherche (Typesense)

La barre de recherche du haut, sur toutes les pages, propose consoles, genres et jeux pendant la frappe (flèches +
Entrée ouvrent la fiche, « Voir les N résultats » ouvre la bibliothèque). Dans la bibliothèque, elle filtre en plus
la liste affichée, combinée aux filtres (console, genre, format, région) et aux tris (dont « Année de sortie » :
du plus ancien au plus récent par défaut, jeux sans année connue à la fin ; le bouton à côté du tri dit l'ordre
en clair, « Plus anciens d'abord », « A → Z »…, et l'inverse d'un clic). Fautes de frappe tolérées
(« castlvania », « zelad », « stret fihgter »), recherche par début de mot (« final fant »), pertinence d'abord
(titre complet, puis nom de fichier, console et genre).

Champ vide : les 6 dernières recherches (Entrée, choix d'une suggestion, « Voir les N résultats », ou saisie qui a
filtré la bibliothèque), à reprendre d'un clic, à retirer une par une ou toutes. Gardées dans le navigateur
(`localStorage`) : le Mac et le téléphone ont chacun leur liste.

Le moteur est [Typesense](https://typesense.org) : Game Manager démarre son propre conteneur Docker
`agm-typesense` (image `typesense/typesense:27.1`), joignable seulement depuis ce Mac sur `127.0.0.1:8118`,
données et clé d'API dans le dossier de données (`typesense/`, `typesense.key`). L'index est reconstruit au
démarrage puis dès que le catalogue change (vérifié toutes les 2 s), sans coupure : « games » est un alias, basculé
sur la nouvelle collection une fois celle-ci remplie. Sans Docker, ou tant que Typesense n'est pas
prêt, la recherche SQLite d'origine prend le relais (`GET /api/search/status` indique le moteur utilisé).
Variables : `AGM_TYPESENSE_URL` et `AGM_TYPESENSE_KEY` pour un autre serveur, `AGM_TYPESENSE=0` pour s'en passer.
API : `GET /api/search?q=…` (recherche rapide), `GET /api/games?q=…` (bibliothèque).

**Jeux ajoutés sans Game Manager** (carte lue sur le Mac, autre outil) : une veille lit chaque minute le dossier des
ROMs, en lecture seule, et relit les dossiers de consoles dont la date a changé ; une console apparue ou disparue
déclenche une synchronisation complète. Au démarrage, elle rattrape ce qui a changé depuis la dernière lecture. Ces
relectures apparaissent dans l'historique des synchronisations avec le déclencheur `watch`. Limite : un fichier
ajouté dans un sous-dossier (jeu multi-disque) n'apparaît qu'à la prochaine synchronisation complète.
`AGM_NO_WATCH=1` coupe la veille.

## Connexion à la console

Une seule connexion SSH, partagée et gardée ouverte 90 s après le dernier usage (`app/device/pool.py`), sert
les jaquettes, les sauvegardes et toutes les commandes (jeu en cours, Bluetooth, temps de jeu, lancement) :
ouvrir une connexion coûte ~0,5 s sur la console, une commande sur la connexion ouverte 0,02 à 0,15 s. Si la
console ne répond pas, les appels suivants échouent aussitôt pendant 15 s au lieu d'attendre chacun le délai
de connexion. Les ajouts de jeux et le test de connexion des Paramètres gardent leur propre connexion.

Paramètres > Connexion guide la mise en route en trois étapes numérotées et cochées : 1. la console (adresse,
utilisateur, puis mot de passe ou clé SSH selon l'authentification choisie, dans le même bloc) ; 2. identifier la
console (comparer puis approuver l'empreinte de sa clé, une fois par console) ; 3. tester la connexion.
Les champs secrets (mot de passe, clés d'API) ont un œil pour afficher ou masquer la saisie. Paramètres > Système
montre d'abord ce que la console sait faire avec son système, par thème (jeux, son, manettes et Bluetooth, temps de
jeu ; ce qui n'est pas possible est barré), puis le choix du système, puis la date et l'heure de la console.

## Autres consoles et systèmes

Game Manager reconnaît le firmware de la console par SSH (quelques `test -d`, lecture seule) ; on peut aussi le
choisir dans Paramètres → « Système de la console ». Chaque profil (`backend/app/device/systems.py`) dit où sont
les ROMs et les sauvegardes, comment lancer et quitter un jeu, et ce qui est disponible ; l'interface masque le reste
(`GET /api/device/system`, `GET /api/systems`, `POST /api/device/system/detect`).

| Profil | Consoles | ROMs | Lancer / quitter depuis le Mac | État |
|---|---|---|---|---|
| Anbernic + Stock OS Mod | RG35XX Pro/Plus/H/SP/2024, RG28XX, RG34XX, RG40XX, RG CubeXX | `/mnt/mmc/Roms` | oui, reprise sur sauvegarde comprise | testé |
| Anbernic d'origine | mêmes consoles, sans le mod | `/mnt/mmc/Roms` | quitter seulement | expérimental |
| Knulli, Batocera | H700, RK3566, Miyoo Flip, TrimUI, PC… | `/userdata/roms` | oui (serveur web d'EmulationStation, port 1234) | expérimental |
| ROCKNIX / JELOS | Anbernic, Powkiddy, Retroid, AYN | `/storage/roms` | quitter ; lancer si le serveur web d'ES répond | expérimental |
| muOS | Anbernic, TrimUI | `/mnt/mmc/ROMS` | quitter | expérimental |
| ArkOS / dArkOS | R36S et clones, RG351, RG353 | `/roms` | quitter | expérimental |
| Onion OS | Miyoo Mini / Mini Plus | `/mnt/SDCARD/Roms` | oui (comme le menu d'Onion), quitter | testé |
| spruce | Miyoo A30, Flip | `/mnt/SDCARD/Roms` | quitter | expérimental |
| MinUI / NextUI | Miyoo, TrimUI, Anbernic | `/mnt/SDCARD/Roms` | non | expérimental |
| Android + RetroArch | Retroid Pocket, AYN Odin/Thor, Anbernic et Ayaneo sous Android | `/storage/emulated/0/ROMs` | lancer (dans RetroArch) ; quitter sur la console | expérimental |
| Autre (Linux + SSH) | — | à régler | quitter (RetroArch) | expérimental |

Noms de dossiers : chaque firmware a les siens (« snes », « SFC », « Super Nintendo Entertainment System (SFC) »,
noms libres sur muOS). `app.platforms.canonical` les ramène à un code commun (`platform.code` dans l'API) pour les
genres, jaquettes, bandes-annonces et illustrations. Les dossiers de médias rangés à côté des ROMs (`images`,
`videos`, `manuals`…) sont ignorés. Quitter un jeu ailleurs que sur Anbernic : commande réseau `QUIT` de RetroArch
(bash ou `nc`), puis `SIGTERM` si RetroArch ne l'écoute pas. Seul le profil Anbernic + Stock OS Mod a été essayé
sur une vraie console ; les autres suivent la documentation de leur firmware.

Onion OS : le menu (MainUI) écrit la commande du jeu dans `/tmp/cmd_to_run.sh` puis se ferme, et la boucle
`.tmp_update/runtime.sh` lance le jeu. `onion_launch.sh` (copié dans `/tmp`) fait pareil : commande au format
de MainUI (émulateur de `Emu/<console>/config.json`), puis fermeture du menu (`SIGTERM`, `SIGKILL` en secours) ; un jeu ouvert est d'abord quitté
(`QUIT` de RetroArch), une appli fermée, le temps que le menu revienne (journal `/tmp/agm-launch.log`). Onion
coupe SSH au lancement des jeux, sauf avec « Keep services alive » (Tweaks > Network) : le script l'active
(`.tmp_update/config/.keepServicesAlive_` renommé en `.keepServicesAlive`, comme le fait Tweaks), seule écriture
sur la carte, pour garder la console joignable pendant la partie (jeu en cours, Quitter).

Android (Retroid, AYN…) : Android n'a pas de serveur SSH, l'application gratuite **Termux** en fournit un (SFTP
compris) ; la bibliothèque, l'ajout de jeux et les sauvegardes marchent alors comme sous Linux. Sur la console, une fois :

1. Installer **Termux** (version F-Droid ou GitHub, pas celle du Play Store, trop ancienne) et **RetroArch**, puis
   télécharger les cœurs utiles (RetroArch → Mise à jour en ligne → Téléchargement de cœurs).
2. Dans Termux : `termux-setup-storage`, `pkg install openssh`, `passwd` (choisir un mot de passe), `sshd`.
3. Réglages Android → Applications → Termux → autoriser **« Afficher par-dessus les autres applis »** (sans cela,
   Android bloque un jeu lancé depuis l'ordinateur pendant que Termux est en arrière-plan).
4. Dans ROMKADE Manager : l'adresse IP de la console, le port **8022**, un nom d'utilisateur quelconque, le mot de passe
   de Termux.

Les jeux se lancent par une intention Android (`am start` vers RetroArch, extras `ROM` et `LIBRETRO` ; un cœur par
console, `ANDROID_CORES` dans `launcher.py`, vérifié sur la liste des cœurs Android de RetroArch). Le jeu en cours ne
se lit pas et ne se quitte pas depuis l'ordinateur : RetroArch pour Android est compilé sans ses commandes réseau
(vérifié sur la 1.22.2) et Android cache ses processus aux autres applications. Indisponible aussi sous Android :
sauvegarder maintenant, reprendre sur une sauvegarde instantanée, volume, Bluetooth, manettes par joueur, heure de la
console (root nécessaire). Essayé sur un émulateur Android 14 (Termux 0.118.3, RetroArch 1.22.2) : connexion,
détection, synchronisation, lancement d'un jeu avec Termux en arrière-plan. Les sauvegardes
sont lues dans `RetroArch/saves` et `RetroArch/states`, à côté du dossier des ROMs (dossiers par défaut de RetroArch
sous Android).

## Version, conditions d'utilisation

- Un seul numéro de version, dans `backend/pyproject.toml` et `frontend/package.json` (vérifié par
  `backend/tests/test_version.py`), affiché dans la barre latérale et dans Paramètres > À propos.
- Conditions d'utilisation sur `/conditions` (lien dans la barre latérale) : ROMKADE ne fournit aucun jeu et ne répond
  pas des manipulations de l'utilisateur sur la console ou sa carte mémoire (perte de données, carte corrompue,
  sauvegardes perdues). Un bandeau les rappelle au premier lancement, jusqu'à « J'ai compris » (`romkade-terms-v1`
  dans le navigateur). Texte à faire relire par un juriste avant une diffusion publique.
- Statistiques d'utilisation anonymes (PostHog Cloud EU), **sur accord** : demandé une fois au premier lancement,
  puis Paramètres > À propos (`romkade-analytics` dans le navigateur). Textes et attributs des éléments masqués,
  adresses réduites au chemin, ni provenance ni enregistrement de session, aucun script externe
  (`frontend/src/lib/analytics.ts`). Proposé seulement si le build reçoit une clé : `VITE_POSTHOG_KEY` (variable du
  dépôt `POSTHOG_KEY` pour l'image Docker, `frontend/.env.local` en développement) ; sans clé, rien n'est demandé ni
  envoyé.
- Logo et icônes ROMKADE Manager (`frontend/src/assets/brand/`, `frontend/public/icon-*.png`), tirés des fichiers de
  marque du dépôt romkade-website.

## Licence

Propriétaire : © 2026 ROMKADE, tous droits réservés (voir [LICENSE](../LICENSE)). Le code est publié pour lecture et
évaluation ; tout autre usage (copie, redistribution, intégration à un produit ou à un firmware, service hébergé)
demande l'accord écrit de ROMKADE. Les composants tiers gardent leur propre licence ([NOTICE](../NOTICE)).

## Sources et crédits

ROMKADE Manager ne fournit aucun jeu. Ce qu'il reprend d'ailleurs est cité dans l'interface
(Paramètres > À propos, liste dans `frontend/src/lib/credits.ts`, et sous chaque fiche de jeu) :

| Source | Usage | Licence |
|---|---|---|
| [libretro-thumbnails](https://github.com/libretro-thumbnails/libretro-thumbnails) | Jaquettes (images © leurs éditeurs) | — |
| [retroarch-assets](https://github.com/libretro/retroarch-assets) | Illustrations des consoles | CC BY 4.0 |
| [libretro-database](https://github.com/libretro/libretro-database) | Genres, sortie, développeur, éditeur, franchise, titres arcade | — |
| [OpenVGDB](https://github.com/OpenVGDB/OpenVGDB) | Résumés, dates, lien GameFAQs, genres | MIT |
| [catver.ini (progettoSNAPS)](https://www.progettosnaps.net/catver/) | Catégories arcade | — |
| MAME, FBNeo, HBMAME | Titres complets, année, fabricant (via libretro-database) | — |
| Wikipédia, GameFAQs, YouTube, l'IA choisie (Claude, ChatGPT, Mistral, Gemini, modèle local) | Liens, bandes-annonces, descriptions et commandes par IA (clés de l'utilisateur) | — |
| [Lucide](https://lucide.dev/), Archivo, Atkinson Hyperlegible Next | Pictogrammes, polices | ISC, SIL OFL 1.1 |

Toute nouvelle source (script `backend/scripts/build_*.py`, service en ligne, illustration) s'ajoute à
`CREDITS` dans `frontend/src/lib/credits.ts`.

Si l'outil vous plaît, une étoile sur [GitHub](https://github.com/RomKade/romkade-manager) aide le projet.

