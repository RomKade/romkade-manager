"""Sauvegardes des jeux sur la console : où elles sont, de quel type, à quel jeu elles appartiennent.

Sur le firmware Anbernic (avec « Stock OS Mod »), les sauvegardes vivent hors du dossier des ROMs, sous
la même carte (BASE = parent de la racine des ROMs, /mnt/mmc) :

- saves_RA/Roms/<CONSOLE>/<cœur>/<jeu>.srm      sauvegarde « en jeu » de RetroArch (pile de la cartouche)
- states_RA/Roms/<CONSOLE>/<cœur>/<jeu>.state   sauvegarde instantanée RetroArch (.state1…, .state.auto)
- save/Roms/<CONSOLE>/…/<jeu.ext>.st0           émulateurs d'origine d'Anbernic (instantanées .stN, .srm)
- save_nds/{backup,savestates}/<jeu>.dsv|.dss   DraStic (Nintendo DS)
- .config/ppsspp/PSP/SAVEDATA/<ID>/…            PPSSPP, un dossier par identifiant de jeu
- Roms/<CONSOLE>/<jeu>.sav                      sauvegarde rangée à côté du jeu (savefiles_in_content_dir)

Les autres firmwares ont leurs propres emplacements (SystemProfile.save_sources, app/device/systems.py) ;
ROCKNIX et ArkOS rangent aussi les sauvegardes instantanées à côté des jeux (states_in_rom_folder).

Lecture seule ici ; les écritures (restauration, suppression) passent par app.device.save_writer.
"""

import posixpath
import re
from dataclasses import dataclass
from datetime import datetime

from app.device.remote_fs import ReadOnlyRemoteFS

# (dossier relatif à BASE, source, profondeur maximale de parcours)
SOURCES: list[tuple[str, str, int]] = [
    ("saves_RA/Roms", "retroarch", 4),
    ("states_RA/Roms", "retroarch", 4),
    ("save/Roms", "stock", 4),
    ("save_nds", "nds", 2),
    (".config/ppsspp/PSP/SAVEDATA", "psp", 2),
]
# Sauvegardes posées à côté des jeux, dans le dossier des ROMs.
ROM_FOLDER_EXT = {"sav", "srm", "dsv", "eep", "fla", "mpk", "sra"}
SRAM_EXT = ROM_FOLDER_EXT | {"nvmem", "nvmem2", "brm", "rtc", "mcd", "mcr"}
# Fichiers d'accompagnement qu'on ne liste pas séparément (miniatures, sommes de contrôle).
COMPANION = re.compile(r"\.(st\d+pic|st\d+crc|gzpic|gzcrc|png)$", re.I)
MAX_FILES = 5000


@dataclass
class SaveFile:
    path: str            # chemin absolu sur la console
    rel: str             # chemin relatif à BASE (sert de nom dans les copies sur le Mac)
    source: str          # retroarch | stock | nds | psp | rom-folder
    kind: str            # sram (sauvegarde en jeu) | state (instantanée)
    slot: str | None     # "0", "1"…, "auto" pour une instantanée
    platform: str | None
    stem: str            # nom du jeu déduit du fichier, pour le rapprochement
    size: int | None
    mtime: datetime | None


def base_dir(roms_root: str) -> str:
    return posixpath.dirname(roms_root.rstrip("/")) or "/"


def classify(name: str) -> tuple[str, str | None, str] | None:
    """(type, emplacement, nom du jeu) d'un fichier de sauvegarde, ou None si ce n'en est pas un."""
    if COMPANION.search(name):
        return None
    low = name.lower()
    if low.endswith(".state.auto"):
        return "state", "auto", name[: -len(".state.auto")]
    m = re.search(r"\.state(\d*)$", name, re.I)
    if m:
        return "state", m.group(1) or "0", name[: m.start()]
    m = re.search(r"\.st(\d+)$", name, re.I)  # émulateurs d'origine
    if m:
        return "state", m.group(1), name[: m.start()]
    m = re.search(r"_(\d+)\.dss$", name, re.I)  # DraStic
    if m:
        return "state", m.group(1), name[: m.start()]
    if low.endswith(".dss"):
        return "state", "0", name[:-4]
    m = re.search(r"(?:\.(\d+))?\.mds(?:\.gz)?$", name, re.I)  # émulateur Mega Drive d'origine
    if m:
        return "state", m.group(1) or "0", name[: m.start()]
    if low.endswith(".save.zip"):  # DOSBox Pure
        return "sram", None, name[: -len(".save.zip")]
    if low.endswith(".gz"):  # instantanées des émulateurs d'origine (Mega Drive)
        return "state", "0", name[:-3]
    m = re.search(r"\.([a-z0-9]+)$", low)
    if m and m.group(1) in SRAM_EXT:
        stem = name[: m.start()]
        if stem.lower().endswith(".zip"):  # Flycast : rumblef2.zip.nvmem
            stem = stem[:-4]
        return "sram", None, stem
    return None


def _platform_of(source: str, rel_in_source: str) -> str | None:
    if source == "nds":
        return "NDS"
    if source == "psp":
        return "PSP"
    head = rel_in_source.split("/", 1)[0]
    return head if "/" in rel_in_source else None


async def _walk(fs: ReadOnlyRemoteFS, path: str, depth: int, out: list) -> None:
    if depth < 0 or len(out) >= MAX_FILES:
        return
    try:
        entries = await fs.listdir(path)
    except Exception:  # noqa: BLE001 — dossier absent ou illisible : rien à lister
        return
    for e in entries:
        if e.kind == "dir":
            await _walk(fs, e.path, depth - 1, out)
        elif e.kind == "file":
            out.append(e)


def _rom_folder_save(name: str, rom_states: bool) -> tuple[str, str | None, str] | None:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in ROM_FOLDER_EXT:
        return "sram", None, name.rsplit(".", 1)[0]
    if rom_states:
        c = classify(name)
        if c and c[0] == "state":
            return c
    return None


async def scan(fs: ReadOnlyRemoteFS, base: str, roms_root: str, platform_dirs: list[str],
               sources=SOURCES, rom_states: bool = False) -> list[SaveFile]:
    """Toutes les sauvegardes connues de la carte. `fs` doit avoir BASE pour racine."""
    found: list[SaveFile] = []
    for rel_root, source, depth in sources:
        root = f"{base.rstrip('/')}/{rel_root}"
        entries: list = []
        await _walk(fs, root, depth, entries)
        for e in entries:
            if source == "psp":
                # PPSSPP : chaque dossier SAVEDATA/<ID> est la sauvegarde d'un jeu ; on liste ses fichiers.
                game_id = e.path[len(root) + 1:].split("/", 1)[0]
                found.append(SaveFile(e.path, e.path[len(base) + 1:], source, "sram", None, "PSP", game_id, e.size, e.modified_at))
                continue
            c = classify(e.name)
            if c is None:
                continue
            kind, slot, stem = c
            found.append(SaveFile(e.path, e.path[len(base.rstrip('/')) + 1:], source, kind, slot,
                                  _platform_of(source, e.path[len(root) + 1:]), stem, e.size, e.modified_at))
    for d in platform_dirs:
        try:
            entries = await fs.listdir(f"{roms_root.rstrip('/')}/{d}")
        except Exception:  # noqa: BLE001
            continue
        for e in entries:
            c = _rom_folder_save(e.name, rom_states) if e.kind == "file" else None
            if c:
                kind, slot, stem = c
                found.append(SaveFile(e.path, e.path[len(base.rstrip('/')) + 1:], "rom-folder", kind, slot, d,
                                      stem, e.size, e.modified_at))
    return found


def is_save_path(path: str, base: str, roms_root: str, sources=SOURCES, rom_states: bool = False) -> bool:
    """Le chemin désigne-t-il un emplacement de sauvegarde (et seulement ça) ? Sert de garde aux écritures."""
    if "\x00" in path or any(seg in ("", ".", "..") for seg in path.split("/")[1:]):
        return False
    norm = posixpath.normpath(path)
    if norm != path:
        return False
    name = posixpath.basename(path)
    for rel_root, source, depth in sources:
        root = f"{base.rstrip('/')}/{rel_root}/"
        if path.startswith(root):
            inner = path[len(root):].split("/")
            if len(inner) > depth + 1:
                return False
            return source == "psp" or classify(name) is not None
    rr = roms_root.rstrip("/") + "/"
    if path.startswith(rr):
        inner = path[len(rr):].split("/")
        return len(inner) == 2 and _rom_folder_save(name, rom_states) is not None
    return False
