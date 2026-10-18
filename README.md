# ROMKADE Manager

<p align="center"><strong>🌐 <a href="https://romkade.com">romkade.com</a></strong></p>

<p align="center"><strong>English</strong> · <a href="README.fr.md">Français</a> · <a href="README.es.md">Español</a></p>

Manage and control your retro handhelds (Anbernic, Miyoo…) from the Mac's browser: library, adding
games, launching on the console, saves, play time, controllers, Bluetooth. **The console is only modified
by actions you start: adding games, restoring or deleting a save, Bluetooth settings and
player controllers.**

Project website: **[romkade.com](https://romkade.com)**.

Architecture, data model and technical choices: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Install with Docker (macOS, Windows, Linux)

1. Install Docker: [Docker Desktop](https://docs.docker.com/desktop/) on macOS and Windows, or
   [Docker Engine](https://docs.docker.com/engine/install/) with the Compose plugin on Linux.
2. Put [`compose.yaml`](compose.yaml) in a folder (for example `romkade`), then in that folder:

```bash
docker compose up -d
```

3. Open http://localhost:8765, then Settings > Connection: console IP address, SSH user and password.

The same image runs on Intel/AMD and ARM (Apple Silicon, Raspberry Pi). The `romkade-data` volume keeps the
catalog, settings, save copies and secrets (`secrets.json`, readable by its owner only), and survives updates:
`docker compose pull && docker compose up -d`. Search (Typesense) is a second service of the same file, with no
published port. The interface only listens on this computer (`127.0.0.1`): do not expose it to the Internet, it
controls your console. The container reaches the console on the local network over SSH: computer and console on
the same network. Data folder outside Docker: `ROMKADE_DATA_DIR` (default per system: `~/Library/Application
Support/AnbernicGameManager`, `%APPDATA%\AnbernicGameManager`, `~/.local/share/AnbernicGameManager`).

## Quick start

```bash
cd romkade-manager
./run.sh
```

The script sets up the Python environment on first run, starts the server and opens
http://127.0.0.1:8765 in the browser. The interface ships already built (`frontend/dist`):
Node is only needed to modify it. `Ctrl+C` stops the server.

## Manual installation (macOS, Apple Silicon)

```bash
cd romkade-manager/backend
# Official python.org Python (signed): Homebrew Python is blocked by the macOS
# "Local Network" permission and returns "No route to host".
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q               # 114 tests against a simulated SFTP server
```

## 1. Diagnose the real console (recommended first)

```bash
.venv/bin/python scripts/diagnose_device.py --host 192.168.86.242
```

The script displays the host key fingerprint, asks for the password (not stored), then checks SFTP, disk space and the directory tree. It writes nothing to the console.

To compare the fingerprint independently:

```bash
ssh-keyscan -p 22 192.168.86.242 2>/dev/null | ssh-keygen -lf -
```

## 2. Sync the catalog (phase 2)

```bash
.venv/bin/python scripts/catalog_report.py
```

On first run: host key confirmation, password stored in the keychain, settings
saved. After that, no questions. The script scans the card read-only, updates
`~/Library/Application Support/AnbernicGameManager/catalog.sqlite3` and prints a report
(games per platform, changes, duplicates, unmatched images).

## 3. Start the application

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Interface: http://127.0.0.1:8765. API documentation: http://127.0.0.1:8765/docs

## Modifying the interface (Node 20 or later: `brew install node`)

```bash
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173, proxies /api to the backend running on 8765
npm test             # Vitest tests
npm run build        # rebuilds frontend/dist, then served by the backend
npm run gen:api      # regenerates the TypeScript types from the OpenAPI spec (backend running)
```

## 4. First connection through the API (not needed if catalog_report.py was run)

```bash
API=http://127.0.0.1:8765/api

# Settings (non-sensitive, stored in ~/Library/Application Support/AnbernicGameManager/)
curl -s -X PUT $API/settings -H 'Content-Type: application/json' \
  -d '{"host":"192.168.86.242","port":22,"username":"root","auth_method":"password","roms_root":"/mnt/mmc/Roms"}'

# Password -> macOS keychain (never returned by the API). read -s keeps it out of the shell history.
read -s PW && curl -s -X PUT $API/settings/password -H 'Content-Type: application/json' \
  -d "{\"password\":\"$PW\"}"; unset PW

# Host key: display, check, then confirm by copying back the fingerprint
curl -s $API/device/host-key
curl -s -X POST $API/device/host-key/trust -H 'Content-Type: application/json' \
  -d '{"fingerprint":"SHA256:...."}'
```

## 5. Usage

Catalog (served from SQLite, even when the console is off):

```bash
curl -s -X POST $API/catalog/sync                       # starts a sync (202 + id)
curl -s $API/catalog/sync/1                             # progress: platforms_done / platforms_total
curl -s $API/catalog/status | python3 -m json.tool      # totals, last sync, card space
curl -s $API/platforms
curl -s "$API/games?q=mario&platform=SFC&sort=name&limit=20"
curl -s "$API/games?region=Europe&extension=chd&has_image=true"
curl -s $API/games/42                                   # details + duplicates + history
open  http://127.0.0.1:8765/api/games/42/image          # Imgs image (cached locally)
curl -s $API/catalog/changes                            # additions / changes / removals from the last sync
curl -s $API/catalog/duplicates
curl -s $API/catalog/unmatched-images
```

Direct access to the console (diagnostics):

```bash
curl -s -X POST $API/device/test-connection | python3 -m json.tool
curl -s $API/device/storage
curl -s "$API/device/inventory?include_files=true&platform=PS"
```

## Adding games

**Add games** page (formerly "Transfers", `/ajouter-des-jeux`): drag files in or click "Choose files".

1. Files are first copied to a staging area on the Mac (`~/Library/Application Support/AnbernicGameManager/staging`), and their SHA-256 hash is computed.
2. For each one, the application suggests the destination console based on the format and flags: name rejected by the card, unusual format, file already present (case-insensitive), title already present, not enough space (minimum 256 MB margin).
3. "Copy to console": each file is written under a hidden temporary name, verified (SHA-256 hash computed on the console, otherwise the size), then renamed. The catalog of the affected consoles is then re-read.
4. An existing file is never replaced without confirmation. When replaced, the old one is moved to `/mnt/mmc/Roms/.agm-backups/<console>/` (same card, no space used). You can delete this folder by hand when you no longer need it.
5. Cancellation or disconnection: the temporary file is deleted, nothing appears on the card. A failed or cancelled transfer can be restarted as long as the file is in the staging area.

## Guarantees

- Reading and writing are separate: `ReadOnlyRemoteFS` for everything that reads, `RemoteWriter` for copies only. Writing is limited to existing console folders (never APPS, PORTS, a symbolic link or a system file), and the only possible deletion concerns the application's temporary files.
- The server rejects requests coming from other sites open in the browser (Origin and Host header checks).
- Host key verified, explicit confirmation on first contact, blocked if it changes.
- Password stored in the macOS keychain only.
- Paths validated and confined under the root, symbolic links reported and never followed.
- `Imgs` folders counted separately, never as games. A `candidate` file is not claimed to be playable.
- Sync: a missing file is marked `deleted_at`, never erased; a platform with an error keeps its files; missing or empty root: sync refused without changing anything.
- Roles: `candidate` (potential game), `component` (.bin track of a .cue, disc of a .m3u), `auxiliary` (text, save), `program` (APPS, PORTS).
- Server bound to 127.0.0.1.

## Genres

The library filters by genre (Sports, Shooter, Platformer…). Genres come from a bundled table,
`backend/app/data/genres.json.gz`, matched by file name: libretro-database for consoles
(No-Intro names), catver.ini (progettoSNAPS) for arcade (MAME short names). No network access at runtime;
genres are recomputed at every startup and after every sync.
Second source: [OpenVGDB](https://github.com/OpenVGDB/OpenVGDB) (OpenEmu's database), essential for
CD-based consoles (PlayStation, Saturn, Mega-CD, PC Engine CD) missing from libretro. Approximate file
names are matched by compact title ("Bomberman2"), stripped prefix ("SS-Clockwork Knight"),
title start (truncated name), then by the same game on another console or in arcade. To refresh the table:

```bash
cd backend && .venv/bin/python scripts/build_genres.py
```

Arcade games show their full title ("sf2.zip" → "Street Fighter II: The World Warrior"),
taken from the MAME, FBNeo and HBMAME lists of libretro-database, in the same table.

## Console illustrations

`frontend/public/consoles/*.webp`: "systematic" XMB theme from
[retroarch-assets](https://github.com/libretro/retroarch-assets) (CC-BY 4.0). To add more:
`cd backend && .venv/bin/python scripts/build_console_icons.py`, then rebuild the interface.

## Trailers

The ▶ button on a cover looks up a video with the official YouTube Data v3 API. It needs a free API key
(Settings → YouTube trailers), stored in the macOS keychain. A search costs
100 units out of a quota of 10,000 per day, i.e. about 100 games per day: the search runs on the first
click, then the result (the 5 most relevant videos) is cached in the catalog. Without a key,
the button opens the search on youtube.com.

## Box art

The images in the card's `Imgs` folder are often composites made for the console's menu. The grid
shows the actual game box instead, taken from [libretro-thumbnails](https://thumbnails.libretro.com)
(RetroArch's image bank), by No-Intro name or, for arcade, by full title. If the exact name
is missing, the closest title is looked up in the bank's file list. Each cover is
downloaded the first time it is displayed, then kept in `cache/boxart` on the Mac; nothing is written to the
card. The library's "Box art / Card images" switch lets you go back to the card's
images.

## Playing on the console from the interface

On a game's page, "Play on the console" closes the menu (or the running RetroArch game, with its
automatic save) and launches the game on the console; the menu comes back when you quit the game.
The console panel, in the sidebar, shows the running game and offers "Quit game".

Works with the Anbernic firmware fitted with the "Stock OS Mod" (`/mnt/mod/ctrl/RA_launch.sh`, cores from
`/mnt/mod/ctrl/configs/CORES.txt`). The script `backend/app/device/launch.sh` is sent over SSH and run
detached: it pauses the menu loop (`/mnt/vendor/ctrl/loadapp.sh`), closes `dmenu.bin` cleanly
(SIGINT), puts the screen back into its boot mode (640×480, 32-bit, saved by the mod in
`configs/fb.cfg`; without this RetroArch cannot display), launches the game the way the mod does, then
releases the loop when the game exits. "Quit game" sends RetroArch's `QUIT` network command
(UDP 55355). No file is written to the card;
the log is in `/tmp/agm-launch.log` on the console.

## Languages

The interface is available in French, English and Spanish (selector at the bottom of the sidebar, choice kept
in the browser). Strings: `frontend/src/i18n/locales/*.ts`, one file per area, the three languages
side by side. The server responds in French; the interface translates its errors from their code.

## Saves

"Saves" page: all the saves on the card, linked to their game, read-only
from the firmware folders (under `/mnt/mmc`):

| Folder | Contents |
|---|---|
| `saves_RA/Roms/<CONSOLE>/<cœur>/` | RetroArch in-game saves (`.srm`, `.save.zip`, `.nvmem`) |
| `states_RA/Roms/<CONSOLE>/<cœur>/` | RetroArch save states (`.state`, `.stateN`, `.state.auto`) |
| `save/Roms/<CONSOLE>/` | Anbernic's stock emulators (`.stN`, `.mds.gz`, `.srm`) |
| `save_nds/` | DraStic (Nintendo DS) |
| `.config/ppsspp/PSP/SAVEDATA/` | PPSSPP (PSP), one folder per game ID |
| `Roms/<CONSOLE>/*.sav` | saves placed next to the game |

- "Copy all saves to the Mac" creates a dated folder in
  `~/Library/Application Support/AnbernicGameManager/save-backups/`, downloadable as a `.zip`.
- Restoring a file from a copy, or deleting a save from the card: refused while a game is running,
  and always preceded by an automatic copy, on the Mac, of the file being replaced or deleted. Writes go
  through `app/device/save_writer.py`, limited to save locations.
- The "How to save" guide shows the RetroArch shortcuts actually configured on the console.
- Dashboard: "Save now" sends RetroArch's `SAVE_STATE` network command to the running game.

## Resuming a game from a save

On the Saves page and on a game's page, each save has a button:
- "Resume here" (RetroArch save state): launches the game on the console, then loads that slot as soon as
  RetroArch is running the game (network commands `GET_STATUS` then `LOAD_STATE_SLOT n`); the
  "auto" state goes through the `auto` option of `RA_launch.sh`;
- "Play" (in-game save): launches the game, which loads its save itself.

## Bluetooth

"Bluetooth" page: the console's Bluetooth status, paired and nearby devices (12 s scan),
pair / connect / disconnect / forget, and "Game sound here" for a speaker or headphones.

- The console has BlueZ and BlueALSA, but nothing starts `bluealsa`: without it a speaker pairs without
  receiving any sound. The application starts it on demand (`bluealsa -p a2dp-source`, detached process).
- "Game sound here": RetroArch is a 32-bit program, BlueALSA's ALSA plugin only exists in 64-bit,
  and RetroArch always opens the "default" ALSA output. The application therefore installs
  `/etc/alsa/conf.d/60-agm-bluetooth.conf` (`agm_bt` output: the sound is passed to `aplay`, 64-bit, towards
  the speaker; if the speaker is absent, the sound is swallowed and the game continues silently) and `/.asoundrc`
  (`pcm.!default agm_bt`, read by games launched from Game Manager, which run with `HOME=/`).
  The relay also copies the sound to the HDMI output (silent without a cable): it gives RetroArch a real-time
  clock; without it ("null" output), the sound came out choppy.
  "Send sound back to the console" deletes these two files. The console's menu, and games launched
  from it, keep using its speakers.
- Recent controllers (Xbox, 8BitDo…): they use Bluetooth Low Energy and only pair during
  an active scan. Connecting is therefore done in a single `bluetoothctl` session (agent, `scan on`, `pair`,
  `trust`, `connect`), logged in `/tmp/agm-bt-connect.log` on the console. If the device is paired but does not
  respond, wake it up (Xbox / Home button) then click "Connect" again.
- The firmware erases pairings at every startup (`/mnt/vendor/ctrl/loadapp.sh` empties
  `/var/lib/bluetooth`), and `bluealsa` is not restarted: after a reboot, reconnect the device from
  this page.

## Controllers

"Controllers" page: who controls the game. Each player's controller in RetroArch (`input_playerN_joypad_index`,
sdl2 driver numbers: 0 = the console's buttons, then USB / Bluetooth controllers in the order they were plugged in).
RetroArch saves its config when quitting: a player 1 left on an old, absent controller prevents the console
from controlling the game ("Use the console buttons" puts it back on player 1). The choice is stored in
`/.config/agm-players`, written right away to `/.config/retroarch/retroarch.cfg` if no game is running, otherwise
by `launch.sh` at the next game launched from Game Manager (once RetroArch is closed). Choosing a controller for a
player swaps it with the player who had it.

RetroArch (sdl2 driver with udev) does not number controllers in the order of `/proc/bus/input/devices` but
by sysfs path: with a USB Xbox controller, `…/soc/5101000.ohci0…` comes before the buttons
`…/soc/soc@03000000:gpio_keys` (Xbox = 0, console = 1), and "player 1 = controller #1" handed control to the
console. `/.config/agm-players` keeps Game Manager's numbers; `players_apply.sh` (run by Game Manager
when no game is running, and by `launch.sh` before each game, with the controllers plugged in at that moment) translates them into
RetroArch's order and also reserves the controller for the player (`input_playerN_reserved_device = "045e:0b12 Generic
X-Box pad"`, type 1 = preferred). What was applied is copied to `/.config/agm-players.applied`; the
result is noted in `/tmp/agm-launch.log` ("joueurs pour RetroArch : 0 045e:0b12 Generic X-Box pad 1 …").

With a controller plugged in on top of the console's buttons, "Play on the console" (game page) first asks
"Who is playing?": the choice becomes player 1, then the game is launched.

The header button follows the situation: a pending change during a RetroArch game known to the
library gives "Restart the game to apply"; a player 1 on an absent controller gives "Use the console
buttons" (then the library when no game is running, or a restart of the running game); otherwise, with no game
running, "Choose a game" opens the library. The restart goes through `launch.sh` again: the game is quit
cleanly with its automatic save, the controllers are written, then it resumes with `auto` if the system can
resume.

## Volume

In the dashboard's "Now playing" block, in the "Now playing" banner of the game page and in the top
bar while a game is running: mute / unmute
and a volume slider (1 to 100% = -40 to 0 dB), working for the speakers as well as for a Bluetooth
speaker.

What does not work on this console, hence this choice:
- the sound chip's mixer: during a game, its settings are locked (`amixer` changes nothing, without an error);
- RetroArch's `VOLUME_UP` / `VOLUME_DOWN` network commands: ignored (only `MUTE` works).

Game Manager therefore adds its own ALSA software volume: `/.asoundrc` (read by games launched from Game
Manager, `HOME=/`) routes the "default" output through two `softvol` (the "Game Manager" volume, then mute),
before the speakers or the Bluetooth output `agm_bt`. The "Game Manager" control appears on card 0 at the
first game after a startup (set to 60% at that point) and is then adjusted with `amixer`, even mid-game. At
launch, `launch.sh` sets RetroArch's own volume (`audio_volume`, often very low) to 0 dB.
A game launched from the console's menu does not use `/.asoundrc`: only muting works (`MUTE`).

## From your phone (ngrok)

```bash
./run.sh --telephone
```

Publishes the interface on an ngrok https address (ngrok account configured once: `ngrok config add-authtoken …`)
and displays the address, the username, the password and a QR code. The application has no accounts: ngrok
asks for the username and password **before** the request reaches the Mac (`basic-auth` rule,
`phone_policy.yml` in the data folder). The password is created on first run
(`phone_password`, readable only by you) and kept afterwards. Besides localhost, the server only accepts
the ngrok address of that run (`AGM_EXTRA_HOSTS`). `Ctrl+C` stops the server and the access. Without `--telephone`,
nothing is published.

## Game information

Game page: genre (icon), regions (flags), release, publisher, developer, franchise (Wikipedia
links in the interface language), summary (in English) and GameFAQs page. Bundled table
`backend/app/data/gameinfo.json.gz`, built by `scripts/build_gameinfo.py` (libretro-database, OpenVGDB,
MAME / FBNeo / HBMAME arcade lists), matched by file name like the genres. Search also finds
the year, publisher, developer, franchise, and the regions and genres in French, English and Spanish
("Japon", "Japan", "Japón").

## Game controls

"Controls" section of the game page: which console button does what in this game ("B: punch",
"A: fire"), with a few tips. "Ask Claude" makes a call (Opus 5.5, medium effort, a few
cents) with the RetroArch cores' default mapping between the original controller and the console's
buttons (Mega Drive: A = Y, B = B, C = A; PlayStation: Cross = B, Circle = A…; arcade: button 1 = B, 2 = A…,
coin = Select). Answer in French, English and Spanish, stored in the database (`game_controls` table, shared by
the editions of the same game). Game the model barely knows: the console's usual controls, flagged as such.
"Edit" / "Write them myself" replaces the list with your own (same text in all three languages). Same AI
API key as the descriptions (Settings > AI).

## Connecting to an AI (LLM)

Settings > AI: a single AI for everything that uses one (game descriptions, game controls).
`backend/app/services/llm.py`:

| Provider | Key | Notes |
|---|---|---|
| Claude (Anthropic) | `sk-ant-…` | Claude Opus 5.5 by default; batch descriptions (half price) |
| ChatGPT (OpenAI), Mistral, Gemini | provider key | OpenAI protocol (chat completions) |
| Other OpenAI-compatible service | optional | address of your choice (`…/v1`) |
| Local model (Ollama, LM Studio) | none | open weights on the Mac, free and offline; `ollama pull qwen2.5:7b` |

- Keys in the macOS keychain, one per provider (the Anthropic key keeps its old entry); otherwise the
  provider's environment variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY`).
- Provider, model and address in `llm.json` (data folder). The model is never guessed: the list
  comes from the provider (`GET /api/settings/llm/models`); "Test" makes a small real request.
- JSON responses: structured outputs (`json_schema`), otherwise plain JSON with the schema in the prompt
  (local models that do not support them).
- Descriptions without Claude: game by game in the background (stops after 5 failures in a row, can be resumed).

## Favorites

"Add to favorites" on a game's page (the open edition). Favorites appear in the dashboard's "My favorites"
(most recently added first, with "Play again") and in the library: "Favorites" button among the
filters, or `/bibliotheque?fav=1` ("All my favorites" link). Stored in the Mac's database (`favorite` table).

Favorites belong to a console: each one records the SHA-256 fingerprint of the console's approved SSH key
(stable, unlike its IP address). Plugging in another console (a friend's, another firmware) only shows its own
favorites, limited to games present on its card; the others stay in the database and come back with their console.

## Play time

"Play time" page: today's time, the last 7 days and the total, 14-day histogram, time per game,
latest sessions; "Today" card on the dashboard.

- **Tracking by Game Manager** (`app/services/playtime.py`): while the server is running, it checks every
  30 s what is running on the console and records dated sessions using the Mac's clock (`play_session`
  table). This is what provides the history and the time per day. `AGM_NO_TRACKER=1` disables it.
- **RetroArch logs** (`/mnt/vendor/deep/retro/playlists/logs/<cœur>/<jeu>.lrtl`): total time per game,
  including games launched from the console's menu. Per-game totals take the larger of the two.
- **Alert** (Settings → Play time): after N hours of the current session or of the day, with an
  optional reminder. It shows as a pop-in in Game Manager and, if checked, on the console's screen during
  the game (RetroArch's `SHOW_MSG` network command). Settings in `play_settings.json` in the data folder.


"From … to …" filter: days, games and sessions in that period. Only sessions tracked by Game Manager
count: RetroArch logs (`.lrtl`) only give a total per game, without dates.

Erasing: a game's trash icon (in "Per game") or "Erase everything", with confirmation. Game
Manager's sessions are deleted; nothing is changed on the console: the game's RetroArch log total at the time of
erasing is recorded (`play_reset` table) and subtracted afterwards, so that only the time played since then counts. The
current session, if affected, starts again from zero.
## Dashboard

In order: the running game, recently played games (▶ button to relaunch them on the console;
the console's RetroArch history supplemented by sessions tracked by Game Manager, `GET /api/play/recent`),
the latest additions with an "Add games" link, the microSD card, then the consoles with the most games and
activity (last session, today's play time, sync, games being added).

## Search (Typesense)

The search bar at the top, on every page, suggests consoles, genres and games as you type (arrows +
Enter open the game page, "See all N results" opens the library). In the library, it also filters
the displayed list, combined with the filters (console, genre, format, region) and the sort options (including "Release year":
oldest to newest by default, games with no known year at the end; the button next to the sort states the order
in plain words, "Oldest first", "A → Z"…, and reverses it in one click). Typos are tolerated
("castlvania", "zelad", "stret fihgter"), prefix search ("final fant"), relevance first
(full title, then file name, console and genre).

Empty field: the last 6 searches (Enter, picking a suggestion, "See all N results", or typing that
filtered the library), to reuse in one click, to remove one by one or all at once. Kept in the browser
(`localStorage`): the Mac and the phone each have their own list.

The engine is [Typesense](https://typesense.org): Game Manager starts its own Docker container
`agm-typesense` (image `typesense/typesense:27.1`), reachable only from this Mac on `127.0.0.1:8118`,
data and API key in the data folder (`typesense/`, `typesense.key`). The index is rebuilt at
startup and then whenever the catalog changes (checked every 2 s), without downtime: "games" is an alias, switched
to the new collection once it is filled. Without Docker, or until Typesense is
ready, the original SQLite search takes over (`GET /api/search/status` shows the engine in use).
Variables: `AGM_TYPESENSE_URL` and `AGM_TYPESENSE_KEY` for another server, `AGM_TYPESENSE=0` to do without it.
API: `GET /api/search?q=…` (quick search), `GET /api/games?q=…` (library).

**Games added without Game Manager** (card read on the Mac, another tool): a watcher reads the ROMs folder every
minute, read-only, and re-reads the console folders whose date has changed; a console appearing or disappearing
triggers a full sync. At startup, it catches up on what changed since the last read. These
re-reads appear in the sync history with the `watch` trigger. Limitation: a file
added in a subfolder (multi-disc game) only appears at the next full sync.
`AGM_NO_WATCH=1` turns off the watcher.

## Connecting to the console

A single SSH connection, shared and kept open 90 s after its last use (`app/device/pool.py`), serves
the box art, the saves and all commands (running game, Bluetooth, play time, launch):
opening a connection costs ~0.5 s on the console, a command on the open connection 0.02 to 0.15 s. If the
console does not respond, subsequent calls fail immediately for 15 s instead of each waiting for the connection
timeout. Game additions and the connection test in Settings keep their own connection.

Settings > Connection guides the setup in three numbered, checked steps: 1. the console (address, user,
then password or SSH key, depending on the chosen authentication, in the same block); 2. identify the console
(compare and approve its key fingerprint, once per console); 3. test the connection.

## Other consoles and systems

Game Manager detects the console's firmware over SSH (a few `test -d`, read-only); you can also
choose it in Settings → "Console system". Each profile (`backend/app/device/systems.py`) says where
the ROMs and saves are, how to launch and quit a game, and what is available; the interface hides the rest
(`GET /api/device/system`, `GET /api/systems`, `POST /api/device/system/detect`).

| Profile | Consoles | ROMs | Launch / quit from the Mac | Status |
|---|---|---|---|---|
| Anbernic + Stock OS Mod | RG35XX Pro/Plus/H/SP/2024, RG28XX, RG34XX, RG40XX, RG CubeXX | `/mnt/mmc/Roms` | yes, including resuming from a save | tested |
| Stock Anbernic | same consoles, without the mod | `/mnt/mmc/Roms` | quit only | experimental |
| Knulli, Batocera | H700, RK3566, Miyoo Flip, TrimUI, PC… | `/userdata/roms` | yes (EmulationStation web server, port 1234) | experimental |
| ROCKNIX / JELOS | Anbernic, Powkiddy, Retroid, AYN | `/storage/roms` | quit; launch if the ES web server responds | experimental |
| muOS | Anbernic, TrimUI | `/mnt/mmc/ROMS` | quit | experimental |
| ArkOS / dArkOS | R36S and clones, RG351, RG353 | `/roms` | quit | experimental |
| Onion OS | Miyoo Mini / Mini Plus | `/mnt/SDCARD/Roms` | yes (like Onion's menu), quit | experimental |
| spruce | Miyoo A30, Flip | `/mnt/SDCARD/Roms` | quit | experimental |
| MinUI / NextUI | Miyoo, TrimUI, Anbernic | `/mnt/SDCARD/Roms` | no | experimental |
| Other (Linux + SSH) | — | to configure | quit (RetroArch) | experimental |

Folder names: each firmware has its own ("snes", "SFC", "Super Nintendo Entertainment System (SFC)",
free-form names on muOS). `app.platforms.canonical` maps them to a common code (`platform.code` in the API) for
genres, box art, trailers and illustrations. Media folders stored next to the ROMs (`images`,
`videos`, `manuals`…) are ignored. Quitting a game on anything other than Anbernic: RetroArch's `QUIT` network command
(bash or `nc`), then `SIGTERM` if RetroArch is not listening. Only the Anbernic + Stock OS Mod profile has been tried
on a real console; the others follow their firmware's documentation.

Onion OS: the menu (MainUI) writes the game's command to `/tmp/cmd_to_run.sh` then closes, and the
`.tmp_update/runtime.sh` loop launches the game. `onion_launch.sh` (copied to `/tmp`) does the same: a command in
MainUI's format (emulator from `Emu/<console>/config.json`), then closing the menu (`SIGTERM`, `SIGKILL` as a fallback); an open game is quit first
(RetroArch's `QUIT`), an app closed, while the menu comes back (log `/tmp/agm-launch.log`). Onion
cuts SSH when games launch, except with "Keep services alive" (Tweaks > Network): the script turns it on
(`.tmp_update/config/.keepServicesAlive_` renamed to `.keepServicesAlive`, as Tweaks does), the only write
to the card, to keep the console reachable during the game (running game, Quit).

## Version, terms of use

- Single version number in `backend/pyproject.toml` and `frontend/package.json` (checked by
  `backend/tests/test_version.py`), shown in the sidebar and in Settings > About.
- Terms of use at `/conditions` (link in the sidebar): ROMKADE provides no games and is not liable for what the user
  does on the console or its memory card (data loss, corrupted card, lost saves). A notice shows them on first launch
  until "Got it" (`romkade-terms-v1` in the browser). Text to have reviewed by a lawyer before public release.
- ROMKADE Manager logo and icons (`frontend/src/assets/brand/`, `frontend/public/icon-*.png`), from the brand files
  of the romkade-website repository.

## Sources and credits

ROMKADE Manager does not provide any games. What it takes from elsewhere is credited in the interface
(Settings > About, list in `frontend/src/lib/credits.ts`, and under each game page):

| Source | Use | License |
|---|---|---|
| [libretro-thumbnails](https://github.com/libretro-thumbnails/libretro-thumbnails) | Box art (images © their publishers) | — |
| [retroarch-assets](https://github.com/libretro/retroarch-assets) | Console illustrations | CC BY 4.0 |
| [libretro-database](https://github.com/libretro/libretro-database) | Genres, release, developer, publisher, franchise, arcade titles | — |
| [OpenVGDB](https://github.com/OpenVGDB/OpenVGDB) | Summaries, dates, GameFAQs link, genres | MIT |
| [catver.ini (progettoSNAPS)](https://www.progettosnaps.net/catver/) | Arcade categories | — |
| MAME, FBNeo, HBMAME | Full titles, year, manufacturer (via libretro-database) | — |
| Wikipedia, GameFAQs, YouTube, the chosen AI (Claude, ChatGPT, Mistral, Gemini, local model) | Links, trailers, AI descriptions and controls (user's own keys) | — |
| [Lucide](https://lucide.dev/), Archivo, Atkinson Hyperlegible Next | Icons, fonts | ISC, SIL OFL 1.1 |

Any new source (`backend/scripts/build_*.py` script, online service, illustration) is added to
`CREDITS` in `frontend/src/lib/credits.ts`.

If you like the tool, a star on [GitHub](https://github.com/arnoweb/romkade-manager) helps the project.

