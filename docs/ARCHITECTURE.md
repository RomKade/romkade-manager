# Anbernic Game Manager : architecture du MVP

## 1. Architecture technique

```text
Navigateur (Mac)  --HTTP/SSE-->  FastAPI (127.0.0.1:8765)
                                   |
                                   +-- api/          routes REST, erreurs structurées, OpenAPI
                                   +-- services/     inventaire, sync (phase 2), transferts (phase 4)
                                   +-- device/       client SSH, façade SFTP en lecture seule, garde de chemins
                                   +-- config + credentials (trousseau macOS via keyring)
                                   +-- SQLite (phase 2) + cache images (phase 5)
                                   |
                                   +--SSH/SFTP (Wi-Fi)--> RG35XX Pro : /mnt/mmc/Roms/
```

Principes structurants :

- **Une seule porte vers la console** : `device/remote_fs.py`. En phase 1 elle n'expose que `listdir`, `stat`, `lstat`, `realpath`, `statvfs`. Aucune méthode d'écriture n'existe, donc aucune route ne peut écrire, même par erreur. La phase 4 ajoutera une façade distincte `WritableRemoteFS` limitée aux sous-dossiers de plateformes.
- **Garde de chemins** : tout chemin est normalisé (POSIX), doit rester sous la racine configurée, refuse `..`, les octets nuls et les segments vides. Les liens symboliques sont signalés, jamais suivis pendant le scan, et un `realpath` vérifie qu'une cible reste sous la racine.
- **Pas de shell construit depuis le navigateur.** Une seule commande distante existe (`df -kP <racine>`, repli si l'extension SFTP `statvfs` manque), avec un chemin validé par regex et `shlex.quote`.
- **Clé d'hôte vérifiée** : fichier `known_hosts` propre à l'application. Premier contact en TOFU explicite : l'API montre l'empreinte SHA256, l'utilisateur la confirme, puis elle est enregistrée. Une clé différente ensuite bloque la connexion (`host_key_mismatch`).
- **Secrets** : mot de passe dans le trousseau macOS (`keyring`, service `anbernic-game-manager`). Les réglages non sensibles vont dans `~/Library/Application Support/AnbernicGameManager/settings.json`, hors du dépôt. L'API n'expose jamais le mot de passe, seulement `has_password`.
- **Connexion par opération** en phase 1 (ouvrir, travailler, fermer). Simple, et la reconnexion est implicite. Un pool avec keepalive viendra avec les transferts, quand des opérations longues le justifieront.
- **Serveur lié à 127.0.0.1.**

## 2. Structure des dossiers

```text
romkade-manager/
├── docs/ARCHITECTURE.md
├── README.md
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py              application FastAPI, gestionnaires d'erreurs
│   │   ├── config.py            réglages (JSON hors dépôt), validation
│   │   ├── credentials.py       trousseau macOS / mémoire (tests)
│   │   ├── errors.py            AppError + codes stables
│   │   ├── schemas.py           modèles Pydantic de l'API
│   │   ├── platforms.py         table dossier -> plateforme (non exhaustive, à valider)
│   │   ├── api/routes.py
│   │   ├── device/
│   │   │   ├── paths.py         garde de chemins
│   │   │   ├── ssh_client.py    connexion AsyncSSH, mapping des erreurs, host key
│   │   │   └── remote_fs.py     façade SFTP lecture seule
│   │   └── services/inventory.py
│   ├── scripts/diagnose_device.py   diagnostic en lecture seule contre la vraie console
│   └── tests/                   serveur SSH/SFTP simulé en mémoire
└── frontend/                    phase 3 (Vite + React + TS)
```

## 3. Modèle de données SQLite

**Implémenté en phase 2** : `device`, `platform`, `remote_file`, `platform_image`, `scan_run`, `scan_change` (migration Alembic `0001`). `storage_volume` est repoussé au multi-carte : l'espace disque est stocké sur `device`. `game`, `game_file_link`, `metadata_source` et `media` arrivent en phase 5, `transfer` en phase 4.

Recherche : `LIKE` sur une clé normalisée (minuscules, sans accents ni ponctuation), 12 ms par requête mesurés sur 6 000 fichiers. FTS5 n'apporte rien à cette échelle et reste une option.

Plan d'origine :

Trois notions séparées, jamais confondues : **fichier présent sur la carte**, **jeu identifié** (métadonnées), **média** (jaquettes, captures).

| Table | Rôle | Colonnes clés |
|---|---|---|
| `device` | une console (prépare le multi-console) | id, name, host, port, username, roms_root, host_key_fingerprint |
| `storage_volume` | une carte microSD (prépare le multi-carte) | id, device_id, label, mount_path, total_bytes, free_bytes, measured_at |
| `platform` | dossier de plateforme | id, volume_id, directory (unique par volume), label, kind (emulated/apps/ports/engine), known |
| `remote_file` | fichier observé sur la carte | id, platform_id, relative_path (unique par plateforme), filename, extension, size, mtime, role (candidate/auxiliary), is_symlink, first_seen_at, last_seen_at, deleted_at, scan_run_id |
| `scan_run` | une synchronisation | id, volume_id, started_at, finished_at, status, files_seen, added, changed, removed, error |
| `scan_change` | journal des différences | id, scan_run_id, remote_file_id, change (added/modified/removed), old_size, new_size, old_mtime, new_mtime |
| `game` | jeu identifié (phase 5) | id, platform_label, normalized_title, title, year, publisher, genre, description, region |
| `game_file_link` | rapprochement fichier -> jeu | remote_file_id, game_id, method (hash/name/manual), confidence, verified |
| `metadata_source` | provenance | id, game_id, provider, external_id, fetched_at, raw_json |
| `media` | cache local | id, game_id, kind (cover/screenshot), local_path, source_url, remote_image_path |
| `transfer` | phase 4 | id, status, local_name, target_platform_id, target_path, size, bytes_done, sha256, error, created_at, finished_at |

Choix :
- **Suppression douce** (`deleted_at`) : un jeu disparu de la carte reste visible comme « absent », rien n'est effacé automatiquement.
- **Doublons** : détection d'abord par `(normalized_title, platform)` et taille, puis par hash (CRC32/SHA1) calculé à la demande seulement, car hasher via SFTP en Wi-Fi coûte une lecture complète.
- **Recherche** : index FTS5 sur `filename` et `normalized_title` pour rester fluide avec des milliers d'entrées.
- **SQLAlchemy 2 + Alembic** : retenus, le schéma va évoluer à chaque phase et les migrations évitent de recréer la base.

## 4. Choix de la bibliothèque SSH/SFTP

| Critère | AsyncSSH | Paramiko | Fabric |
|---|---|---|---|
| Asynchrone natif (FastAPI) | oui | non, threads nécessaires | non |
| SFTP avec requêtes en pipeline (débit Wi-Fi) | oui (`block_size`, `max_requests`) | séquentiel par défaut, lent | via Paramiko |
| Progression de transfert | callback `progress_handler` | callback | callback |
| Extension `statvfs@openssh.com` | oui | oui | via Paramiko |
| `known_hosts` et récupération de clé sans auth | oui (`get_server_host_key`) | partiel | partiel |
| Serveur SSH/SFTP embarquable pour les tests | oui | limité | non |

**Retenu : AsyncSSH.** Il s'intègre à la boucle asyncio de FastAPI sans pool de threads, pipeline les requêtes SFTP (gain net sur Wi-Fi pour les gros `.chd`), et fournit un serveur SFTP en mémoire qui permet de tester le backend sans la console.

Point à vérifier sur la console : la présence du sous-système SFTP. Certains firmwares utilisent Dropbear sans `sftp-server`. Le script `scripts/diagnose_device.py` le teste ; l'API renvoie `sftp_unavailable` si besoin. Repli éventuel (à ne coder que si nécessaire) : SCP, également supporté par AsyncSSH.

## 5. Plan de la phase 1

1. Squelette FastAPI, erreurs structurées, liaison 127.0.0.1. **Fait.**
2. Réglages + trousseau + vérification de clé d'hôte (TOFU explicite). **Fait.**
3. Client AsyncSSH, mapping des erreurs (injoignable, auth, clé, SFTP absent). **Fait.**
4. Façade SFTP lecture seule + garde de chemins. **Fait.**
5. Listing des plateformes et des fichiers en JSON, exclusion de `Imgs`, des fichiers cachés et AppleDouble. **Fait.**
6. Espace disque (`statvfs`, repli `df`). **Fait.**
7. Tests contre un serveur simulé qui enregistre toute tentative d'écriture. **Fait.**
8. **À faire par toi** : lancer `diagnose_device.py` sur la vraie console et me renvoyer la sortie, pour valider SFTP, `statvfs`, l'arborescence réelle et les formats observés avant la phase 2.

## 6. Constats sur la vraie console (diagnostic du 16/10/2026)

- Système : Ubuntu 22.04, noyau 4.9.170 aarch64, **OpenSSH** (`sshd` + `/usr/lib/openssh/sftp-server`). SFTP v3 opérationnel.
- Clé d'hôte : RSA 3072, `SHA256:H2oR6phcGMrp1lTmz5PKY+FZpA+6HriogZv2T/We6wo` (vérifiée avec `ssh-keyscan`). Ne pas forcer l'algorithme `ssh-rsa` (SHA-1) : la console coupe la connexion, il faut laisser négocier `rsa-sha2-*`.
- Espace : `statvfs@openssh.com` supporté, repli `df` inutile en pratique. 47,2 Go au total, 15,0 Go libres.
- Inventaire : 55 dossiers, 5 696 fichiers, 30,5 Go, **9,3 s de scan en direct** : le cache SQLite est nécessaire pour l'interface.
- `APPS` et `PORTS` contiennent des programmes (`.py`, `.json`, `.deb`, ressources de jeux portés), pas des ROMs : à traiter au niveau dossier, hors catalogue de jeux.
- Les dossiers `Imgs` contiennent souvent plus d'images que de jeux (A2600 : 593 images pour 103 jeux) : rapprochement image/jeu par nom de fichier à prévoir, images orphelines à signaler.
- Formats observés : `.chd`, `.pbp` (PS), `.zip` (arcade), `.v64/.z64/.n64`, `.iso/.cso`, `.smc/.sfc`, `.md/.bin`, `.rom` (MSX), `.p8`, `.mgw`, `.pak`. Un `.sav` en GBA, correctement classé auxiliaire.
- Poste de travail : sous macOS 15, Python Homebrew bloqué par la permission « Réseau local » (`No route to host`). Python python.org 3.13 fonctionne.

## 7. Phase 2 : décisions

- Sync en tâche asyncio, une seule à la fois (`409 sync_already_running`), progression lisible par plateforme. Au redémarrage du serveur, une sync restée `running` passe en `interrupted`.
- Écritures SQLite en un flush par plateforme : 1,8 s pour un premier import de 6 000 fichiers, 0,9 s pour une resynchronisation. Le temps total reste dominé par le scan SFTP (environ 9 s).
- Identifiant de jeu = `remote_file.id`, stable entre synchronisations ; un fichier revenu sur la carte retrouve son identifiant (`restored`).
- Images : rapprochement exact par nom (sans extension, casse ignorée) entre un jeu et une image d'un dossier `Imgs` de la même plateforme. Les images non rapprochées sont listées (`/api/catalog/unmatched-images`) pour affiner la règle sur la base des noms réels. Les images sont lues en `rb` par SFTP puis mises en cache sous `cache/images/`, clé incluant taille et date.
- Doublons : même titre normalisé dans une plateforme ; `likely` si même taille, sinon `possible` (régions ou versions).
- `metadata_status = not_fetched` partout : état explicite tant que la phase 5 n'a pas tourné.

## 8. Phase 3 : interface web

- **Pile** : React 19, TypeScript strict, Vite, Radix UI (Dialog, Popover, Select, ToggleGroup, Checkbox), TanStack Query pour les données serveur et TanStack Virtual pour la grille et le tableau. Types de l'API générés depuis l'OpenAPI (`openapi-typescript`) : un changement de schéma casse la compilation au lieu de casser l'écran.
- **Un seul port** : FastAPI sert `frontend/dist` (repli SPA pour les routes de l'interface, `/api` et `/docs` exclus). L'interface compilée est livrée, Node n'est requis que pour la développer.
- **Connexion partagée** (`device/pool.py`) : une seule connexion SSH/SFTP réutilisée par toutes les lectures de jaquettes, fermée après 90 s d'inactivité. Sans elle, une grille de 40 jaquettes ouvrirait 40 connexions et la console en refuserait la plupart. Testé : 30 jaquettes demandées en rafale ouvrent une seule connexion.
- **Miniatures** : la grille demande `?size=thumb`, une WebP de 360 px générée par Pillow et mise en cache à côté de l'original. Une image illisible est servie telle quelle.
- **Hors ligne** : catalogue, filtres et jaquettes déjà vues restent disponibles console éteinte ; une jaquette jamais vue affiche les initiales du jeu.
- **État dans l'URL** : recherche, filtres, tri et vue sont dans l'adresse (`/bibliotheque?platform=SFC&sort=size`), donc conservés au retour arrière et partageables entre onglets.
- **Facettes** : `GET /api/catalog/facets` fournit formats et régions disponibles, avec leur nombre de jeux, pour la plateforme filtrée.
- **Design** : coque gris clair inspirée de la console, grille des jaquettes dans une « dalle » sombre encadrée, prune des boutons A/B pour les actions. Titres en Archivo élargi, texte en Atkinson Hyperlegible avec les chiffres d'Archivo (le zéro barré d'Atkinson se lisait « Ø »). Thème sombre automatique. Palette de la barre d'occupation de la carte validée pour le daltonisme et le contraste dans les deux thèmes.
- **Vérification** : 12 tests Vitest (formatage, état d'URL, barre de stockage, recherche, fiche, console hors ligne) et contrôle visuel par captures sur une console simulée (clair, sombre, mobile, hors ligne).

## 9. Phase 4 : transferts

- **Deux étapes** : le navigateur envoie le fichier au serveur local (`PUT /api/uploads`, corps brut, empreinte SHA-256 calculée à la réception), puis le serveur le copie par SFTP. Le navigateur ne voit jamais la console.
- **Plan sans écriture** (`POST /api/transfers/plan`) : destination proposée d'après les formats réellement présents sur la carte et une table de formats usuels (pas de suggestion si le format sert à plusieurs consoles, comme .zip ou .bin) ; nom validé pour exFAT (caractères interdits, longueur, fichier caché) ; homonyme exact ou à la casse près ; titre déjà présent ; deux fichiers identiques dans le même lot ; espace libre avec marge (max 256 Mo, 1 % de la carte). Le plan est recalculé côté serveur au lancement, puis chaque fichier est revérifié juste avant l'écriture.
- **Écriture** (`RemoteWriter`) : dossier de plateforme existant uniquement, ni APPS, ni PORTS, ni lien symbolique ; fichier temporaire `.agm-<jeton>.part` ; contrôle de taille puis `sha256sum` sur la console (le nom du fichier temporaire est généré par le serveur, aucun texte venant du navigateur n'entre dans la commande) ; repli sur la taille si `sha256sum` est absent ; renommage final. Remplacement : confirmation explicite obligatoire (`confirm_overwrite`), ancien fichier déplacé dans `.agm-backups/<plateforme>/` puis restauré si le renommage échoue. « Garder les deux » produit `Nom (2).ext`.
- **Nettoyage** : annulation ou erreur, le temporaire est supprimé sur la même connexion ; après une coupure, les temporaires orphelins sont supprimés au prochain envoi vers ce dossier (motif strict, rien d'autre).
- **File d'attente** : un fichier à la fois, sur sa propre connexion SSH (les jaquettes gardent la leur). Un transfert en attente peut être annulé avant de commencer. Au redémarrage du serveur, les transferts en cours passent à « interrompu » et peuvent être relancés.
- **Catalogue** : à la fin de la file, seules les consoles modifiées sont relues (`scan_run.trigger = transfer`), sans marquer les autres comme disparues.
- **Suivi en direct** : flux Server-Sent Events `GET /api/transfers/events` (progression, débit, temps restant).
- **Sécurité navigateur** : `LocalOnlyMiddleware` refuse les requêtes dont l'en-tête Host n'est pas local (DNS rebinding) et toute modification venant d'une autre origine que l'interface.
- **Migration** : Alembic `0002` ajoute la table `transfer` et `scan_run.trigger` ; une base de la phase 2 est mise à niveau au démarrage, sans perte (testé).
- **Tests** : 114 backend (dont 33 sur les transferts et 7 sur la sécurité) et 13 interface ; copie de bout en bout vérifiée dans le navigateur sur une console simulée inscriptible (plan, choix de console, remplacement confirmé avec sauvegarde, fichier ignoré, catalogue mis à jour).
