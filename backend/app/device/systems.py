"""Systèmes des consoles : chaque firmware range les jeux et les sauvegardes à sa façon et se pilote autrement.

Un profil décrit un firmware : où sont les ROMs, où sont les sauvegardes, comment lancer et quitter un jeu,
ce qui est disponible (Bluetooth, journaux de RetroArch…). Le profil est détecté par SSH (lecture seule,
quelques `test -d`) ou choisi dans les Paramètres.

Seul le firmware Anbernic avec « Stock OS Mod » a été essayé sur une vraie console (RG35XX Pro) ; les autres
profils suivent la documentation de leur firmware et sont marqués « experimental ».
"""

import re
import shlex
from dataclasses import asdict, dataclass, field

from app.device.launcher import Runner
from app.device.ssh_client import DeviceClient

ES_HTTP = "http://127.0.0.1:1234"  # serveur web d'EmulationStation (Batocera, Knulli)
SaveSource = tuple[str, str, int]  # (dossier relatif au dossier parent des ROMs, source, profondeur)

STOCK_SAVES: tuple[SaveSource, ...] = (
    ("saves_RA/Roms", "retroarch", 4),
    ("states_RA/Roms", "retroarch", 4),
    ("save/Roms", "stock", 4),
    ("save_nds", "nds", 2),
    (".config/ppsspp/PSP/SAVEDATA", "psp", 2),
)


@dataclass(frozen=True)
class SystemProfile:
    id: str
    label: str
    status: str                       # tested | experimental
    roms_roots: tuple[str, ...]       # emplacements habituels du dossier des ROMs, dans l'ordre
    launcher: str | None              # stock-mod | es-http | onion | None (lancement à distance impossible)
    quit: str                         # ra-udp (Anbernic) | es-http (repli : generic) | generic (QUIT puis SIGTERM) | none
    save_sources: tuple[SaveSource, ...] = ()
    states_in_rom_folder: bool = False  # sauvegardes instantanées rangées à côté des jeux
    ra_config: str | None = None
    ra_history: str | None = None
    ra_logs: str | None = None
    bluetooth: str | None = None      # stock (BlueZ + pont audio) | bluez (appairage seul) | None
    notes: str = ""
    makers: tuple[str, ...] = field(default=())
    ra_network: bool = False          # commandes réseau de RetroArch actives (SAVE_STATE, SHOW_MSG)

    def capabilities(self, es_http: bool = False) -> dict[str, bool]:
        launch = self.launcher in ("stock-mod", "onion") or (self.launcher == "es-http" and es_http)
        return {
            "launch": launch,
            "resume_slot": self.launcher == "stock-mod",
            "quit": self.quit != "none",
            "save_state": self.ra_network,
            "now_playing": True,
            "saves": True,  # au pire, les sauvegardes rangées à côté des jeux
            "retroarch_logs": self.ra_logs is not None,
            "bluetooth": self.bluetooth is not None,
            "bluetooth_audio": self.bluetooth == "stock",
            "players": self.bluetooth == "stock",
            "volume": self.bluetooth == "stock",  # mixeur de la puce son du firmware d'origine (app/device/volume.py)  # firmware d'origine : config RetroArch fixe (app/device/players.py)
            "on_screen_message": self.ra_network,
        }


PROFILES: dict[str, SystemProfile] = {p.id: p for p in [
    SystemProfile(
        "anbernic-stock-mod", "Anbernic (firmware d'origine + Stock OS Mod)", "tested",
        ("/mnt/mmc/Roms", "/mnt/sdcard/Roms"), "stock-mod", "ra-udp", STOCK_SAVES,
        ra_config="/.config/retroarch/retroarch.cfg", ra_history="/.config/retroarch/content_history.lpl",
        ra_logs="/mnt/vendor/deep/retro/playlists/logs", bluetooth="stock", ra_network=True,
        notes="RG35XX Pro/Plus/H/SP/2024, RG28XX, RG34XX, RG40XX, RG CubeXX (puce H700).", makers=("Anbernic",)),
    SystemProfile(
        "anbernic-stock", "Anbernic (firmware d'origine)", "experimental",
        ("/mnt/mmc/Roms", "/mnt/sdcard/Roms"), None, "ra-udp", STOCK_SAVES,
        ra_config="/.config/retroarch/retroarch.cfg", ra_history="/.config/retroarch/content_history.lpl",
        ra_logs="/mnt/vendor/deep/retro/playlists/logs", bluetooth="stock", ra_network=True,
        notes="Sans « Stock OS Mod », les jeux ne se lancent pas à distance : installer le mod de cbepx-me.",
        makers=("Anbernic",)),
    SystemProfile(
        "knulli", "Knulli", "experimental", ("/userdata/roms",), "es-http", "es-http",
        (("saves", "retroarch", 3),), ra_config="/userdata/system/configs/retroarch/retroarchcustom.cfg",
        bluetooth="bluez", ra_network=True, notes="Basé sur Batocera. Consoles H700 (Anbernic), RK3566, Miyoo Flip, TrimUI.",
        makers=("Anbernic", "Miyoo", "TrimUI", "Powkiddy")),
    SystemProfile(
        "batocera", "Batocera", "experimental", ("/userdata/roms",), "es-http", "es-http",
        (("saves", "retroarch", 3),), ra_config="/userdata/system/configs/retroarch/retroarchcustom.cfg",
        bluetooth="bluez", ra_network=True, makers=("PC", "Raspberry Pi", "Retroid")),
    # Vérifié sur le système de l'image officielle (systems-lab/rocknix) : .srm à côté du jeu, instantanées dans
    # roms/savestates/<console> (setsettings.sh), commandes réseau de RetroArch coupées, serveur web d'ES présent.
    SystemProfile(
        "rocknix", "ROCKNIX / JELOS", "experimental", ("/storage/roms",), "es-http", "es-http",
        (("roms/savestates", "retroarch", 2),), ra_config="/storage/.config/retroarch/retroarch.cfg",
        ra_history="/storage/playlists/builtin/content_history.lpl", ra_logs="/storage/playlists/logs",
        bluetooth="bluez", ra_network=False,
        notes="Sauvegardes en jeu à côté des jeux, instantanées dans roms/savestates. Sauvegarder depuis le Mac : "
              "impossible (commandes réseau de RetroArch coupées) ; RetroArch sauvegarde tout seul en quittant.",
        makers=("Anbernic", "Powkiddy", "Retroid", "AYN")),
    SystemProfile(
        "muos", "muOS", "experimental", ("/mnt/mmc/ROMS", "/mnt/sdcard/ROMS", "/mnt/union/ROMS"), None, "generic",
        (("MUOS/save/file", "retroarch", 3), ("MUOS/save/state", "retroarch", 3)),
        ra_config="/mnt/mmc/MUOS/retroarch/retroarch.cfg",
        notes="Dossiers de ROMs aux noms libres : la console de chaque dossier est devinée d'après son nom.",
        makers=("Anbernic", "TrimUI")),
    SystemProfile(
        "arkos", "ArkOS / dArkOS", "experimental", ("/roms", "/roms2"), None, "generic",
        (), states_in_rom_folder=True, ra_config="/home/ark/.config/retroarch/retroarch.cfg",
        ra_history="/home/ark/.config/retroarch/content_history.lpl",
        notes="R36S et clones, RG351, RG353 (sous ArkOS).", makers=("Anbernic", "R36S", "Powkiddy")),
    SystemProfile(
        "onion", "Onion OS", "experimental", ("/mnt/SDCARD/Roms",), "onion", "generic",
        (("Saves/CurrentProfile/saves", "retroarch", 3), ("Saves/CurrentProfile/states", "retroarch", 3)),
        ra_config="/mnt/SDCARD/RetroArch/.retroarch/retroarch.cfg",
        ra_history="/mnt/SDCARD/Saves/CurrentProfile/lists/content_history.lpl",
        notes="Miyoo Mini / Mini Plus. Activer SSH dans les réglages d'Onion. Au premier jeu lancé depuis le Mac, "
              "Game Manager active « Keep services alive » (Tweaks > Network) : sans lui, Onion coupe SSH pendant "
              "les jeux.",
        makers=("Miyoo",)),
    SystemProfile(
        "spruce", "spruce", "experimental", ("/mnt/SDCARD/Roms",), None, "generic",
        (("Saves/saves", "retroarch", 3), ("Saves/states", "retroarch", 3)),
        ra_config="/mnt/SDCARD/RetroArch/retroarch.cfg", notes="Miyoo A30, Miyoo Flip, TrimUI.",
        makers=("Miyoo", "TrimUI")),
    SystemProfile(
        "minui", "MinUI / NextUI", "experimental", ("/mnt/SDCARD/Roms",), None, "none",
        (("Saves", "minui", 2),),
        notes="Dossiers « Game Boy (GB) » : la console est lue entre parenthèses. Pas de RetroArch.",
        makers=("Miyoo", "TrimUI", "Anbernic")),
    SystemProfile(
        "generic", "Autre système (Linux + SSH)", "experimental", (), None, "generic", (),
        notes="Catalogue, jaquettes, ajout de jeux et sauvegardes rangées à côté des jeux.", makers=()),
]}
DEFAULT_PROFILE = "anbernic-stock-mod"
ALL_ROOTS = sorted({r for p in PROFILES.values() for r in p.roms_roots})

DETECT_COMMAND = (
    "grep -hE '^(NAME|ID|OS_NAME)=' /etc/os-release 2>/dev/null | sed 's/^/os./'; "
    "test -x /mnt/mod/ctrl/RA_launch.sh && echo m=stockmod; "
    "test -d /mnt/vendor/ctrl && echo m=anbernic; "
    "test -f /usr/share/batocera/batocera.version && { echo m=batocera; "
    "grep -qi knulli /usr/share/batocera/batocera.version /etc/hostname 2>/dev/null && echo m=knulli; }; "
    "test -d /opt/muos && echo m=muos; "
    "test -d /home/ark && echo m=arkos; "
    "test -d /mnt/SDCARD/.tmp_update && echo m=onion; "
    "test -d /mnt/SDCARD/spruce && echo m=spruce; "
    "test -d /mnt/SDCARD/.system && echo m=minui; "
    "command -v bluetoothctl >/dev/null 2>&1 && echo m=bluez; "
    "command -v bash >/dev/null 2>&1 && echo m=bash; "
    f"(curl -s -m 2 {ES_HTTP}/caps || wget -q -T 2 -O - {ES_HTTP}/caps) >/dev/null 2>&1 && echo m=eshttp; "
    f"for d in {' '.join(shlex.quote(r) for r in ALL_ROOTS)}; do test -d \"$d\" && echo root=$d; done; true"
)


@dataclass
class Detection:
    profile: str
    markers: list[str]
    os_name: str | None
    roms_roots: list[str]
    es_http: bool


def parse_detection(out: str) -> Detection:
    markers, roots, os_info = [], [], {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("m="):
            markers.append(line[2:])
        elif line.startswith("root="):
            roots.append(line[5:])
        elif line.startswith("os.") and "=" in line:
            k, _, v = line[3:].partition("=")
            os_info[k] = v.strip().strip('"')
    os_id = " ".join(os_info.get(k, "") for k in ("ID", "NAME", "OS_NAME")).lower()  # ROCKNIX : OS_NAME seul
    m = set(markers)
    if "stockmod" in m:
        profile = "anbernic-stock-mod"
    elif "anbernic" in m:
        profile = "anbernic-stock"
    elif "knulli" in m or "knulli" in os_id:
        profile = "knulli"
    elif "batocera" in m or "batocera" in os_id:
        profile = "batocera"
    elif re.search(r"rocknix|jelos", os_id):
        profile = "rocknix"
    elif "muos" in m:
        profile = "muos"
    elif "arkos" in m:
        profile = "arkos"
    elif "onion" in m:
        profile = "onion"
    elif "spruce" in m:
        profile = "spruce"
    elif "minui" in m:
        profile = "minui"
    else:
        profile = "generic"
    return Detection(profile, markers, os_info.get("NAME") or os_info.get("OS_NAME"), roots, "eshttp" in m)


async def detect(run: Runner, client: DeviceClient) -> Detection:
    _, out = await run(client, DETECT_COMMAND, timeout=15)
    return parse_detection(out)


def suggested_root(profile: SystemProfile, found: list[str]) -> str | None:
    """Le premier emplacement habituel du profil présent sur la console, sinon le premier trouvé."""
    for r in profile.roms_roots:
        if r in found:
            return r
    return found[0] if found else None


class SystemService:
    """Profil en vigueur : celui choisi dans les Paramètres, sinon celui détecté (gardé en mémoire)."""

    def __init__(self, settings_store, runner_factory, client_factory):
        self.settings_store = settings_store
        self.runner_factory = runner_factory
        self.client_factory = client_factory
        self.detection: Detection | None = None

    def chosen(self) -> str:
        return getattr(self.settings_store.load(), "system", "auto")

    def profile(self) -> SystemProfile:
        """Profil sans contacter la console. Tant que rien n'est détecté : le profil par défaut (testé)."""
        choice = self.chosen()
        if choice in PROFILES:
            return PROFILES[choice]
        if self.detection:
            return PROFILES[self.detection.profile]
        return PROFILES[DEFAULT_PROFILE]

    def es_http(self) -> bool:
        return bool(self.detection and self.detection.es_http)

    async def refresh(self) -> Detection:
        self.detection = await detect(self.runner_factory(), self.client_factory())
        return self.detection

    async def ensure(self) -> SystemProfile:
        """Profil en vigueur ; détecte une fois par SSH si besoin (choix « auto » ou serveur web à sonder)."""
        chosen = self.chosen()
        needs_probe = chosen == "auto" or PROFILES[chosen].launcher == "es-http"
        if self.detection is None and needs_probe:
            try:
                await self.refresh()
            except Exception:  # noqa: BLE001 — console éteinte : profil choisi ou par défaut
                pass
        return self.profile()

    def describe(self) -> dict:
        p = self.profile()
        d = self.detection
        return {
            "chosen": self.chosen(),
            "profile": profile_out(p),
            "capabilities": p.capabilities(self.es_http()),
            "detected": None if d is None else {
                "profile": d.profile, "label": PROFILES[d.profile].label, "os_name": d.os_name,
                "roms_roots": d.roms_roots, "suggested_roms_root": suggested_root(PROFILES[d.profile], d.roms_roots),
                "es_http": d.es_http,
            },
        }


def profile_out(p: SystemProfile) -> dict:
    out = asdict(p)
    out["save_sources"] = [s[0] for s in p.save_sources]
    out["capabilities"] = p.capabilities(es_http=p.launcher == "es-http")
    return out
