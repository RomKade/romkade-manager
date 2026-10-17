"""Plan d'un transfert : destination, conflits, format, espace. Rien n'est écrit ici.

Le plan est recalculé côté serveur au moment de lancer les transferts, puis vérifié une dernière fois
fichier par fichier au moment de l'écriture : ce que le navigateur a vu n'est jamais pris pour acquis.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import errors
from app.db.models import Platform, RemoteFile
from app.device.remote_writer import FORBIDDEN_TARGETS, RemoteWriter
from app.platforms import lookup
from app.services.classify import extension_of, normalize_title, stem_of
from app.services.staging import StagingStore, validate_filename

# Formats usuels par dossier (indicatif : complété par les formats réellement présents sur la carte).
KNOWN_EXTENSIONS: dict[str, set[str]] = {
    "FC": {"nes", "unf", "zip"}, "FDS": {"fds", "zip"}, "SFC": {"smc", "sfc", "zip"},
    "MD": {"md", "bin", "gen", "smd", "zip"}, "SMS": {"sms", "zip"}, "GG": {"gg", "zip"},
    "SEGA32X": {"32x", "zip"}, "MDCD": {"chd", "cue", "m3u"}, "SATURN": {"chd", "cue", "m3u"},
    "DREAMCAST": {"chd", "gdi", "cdi", "m3u"}, "GB": {"gb", "zip"}, "GBC": {"gbc", "gb", "zip"},
    "GBA": {"gba", "zip"}, "NDS": {"nds", "zip"}, "N64": {"z64", "n64", "v64", "zip"}, "VB": {"vb"},
    "PS": {"chd", "pbp", "cue", "m3u", "iso", "img"}, "PSP": {"iso", "cso", "pbp", "chd"},
    "PCE": {"pce", "zip"}, "PCECD": {"chd", "cue", "m3u"}, "NGP": {"ngp", "ngc", "zip"},
    "WS": {"ws", "wsc", "zip"}, "LYNX": {"lnx", "zip"}, "MSX": {"rom", "mx1", "mx2", "dsk"},
    "A2600": {"a26", "bin"}, "A5200": {"a52"}, "A7800": {"a78"}, "GW": {"mgw"}, "PICO": {"p8", "png"},
    "POKE": {"min"}, "C64": {"d64", "t64", "prg", "crt"}, "OPENBOR": {"pak"},
    "MAME": {"zip", "7z"}, "FBNEO": {"zip", "7z"}, "HBMAME": {"zip"}, "CPS1": {"zip"}, "CPS2": {"zip"},
    "CPS3": {"zip"}, "NEOGEO": {"zip"}, "NEOCD": {"chd", "cue"}, "ATOMISWAVE": {"zip"}, "NAOMI": {"zip"},
    "PGM2": {"zip"}, "VARCADE": {"zip"},
}

SPACE_MARGIN_MIN = 256 * 1024**2  # garder au moins 256 Mio libres
SPACE_MARGIN_RATIO = 0.01          # ou 1 % de la carte


@dataclass
class PlanItem:
    upload_id: str
    filename: str
    size: int
    platform: str | None
    platform_label: str | None
    platform_choices: list[str] = field(default_factory=list)
    conflict: dict | None = None        # fichier du même nom déjà sur la carte
    warnings: list[dict] = field(default_factory=list)
    error: dict | None = None           # bloquant pour ce fichier

    @property
    def blocking(self) -> bool:
        return self.error is not None


@dataclass
class Plan:
    items: list[PlanItem]
    total_bytes: int
    free_bytes: int | None
    margin_bytes: int
    fits: bool | None


def extension_stats(s: Session) -> dict[str, dict[str, int]]:
    """extension -> {plateforme: nombre de jeux} d'après le catalogue."""
    out: dict[str, dict[str, int]] = defaultdict(dict)
    rows = s.execute(select(RemoteFile.extension, Platform.directory, func.count(RemoteFile.id)).join(Platform)
                     .where(RemoteFile.deleted_at.is_(None), RemoteFile.role.in_(("candidate", "component")),
                            RemoteFile.extension.is_not(None))
                     .group_by(RemoteFile.extension, Platform.directory))
    for ext, plat, n in rows:
        out[ext][plat] = n
    return out


def suggest_platform(ext: str | None, stats: dict[str, dict[str, int]], existing: set[str]) -> tuple[str | None, list[str]]:
    """Plateforme suggérée et choix possibles. Pas de suggestion si l'extension est ambiguë (.zip, .bin…)."""
    if not ext:
        return None, []
    observed = {p: n for p, n in stats.get(ext, {}).items() if p in existing}
    known = sorted(p for p, exts in KNOWN_EXTENSIONS.items() if ext in exts and p in existing)
    choices = sorted(set(observed) | set(known), key=lambda p: (-observed.get(p, 0), p))
    if not choices:
        return None, []
    if len(choices) == 1:
        return choices[0], choices
    total = sum(observed.values())
    top = choices[0]
    if total and observed.get(top, 0) / total >= 0.9 and len(known) <= 1:
        return top, choices
    return None, choices


def allowed_extensions(platform: str, stats: dict[str, dict[str, int]]) -> set[str]:
    seen = {ext for ext, plats in stats.items() if platform in plats}
    return seen | KNOWN_EXTENSIONS.get(platform, set())


def same_title_files(s: Session, platform: str, filename: str) -> list[str]:
    title = normalize_title(stem_of(filename))
    if not title:
        return []
    return list(s.scalars(select(RemoteFile.filename).join(Platform).where(
        Platform.directory == platform, RemoteFile.normalized_title == title, RemoteFile.role == "candidate",
        RemoteFile.deleted_at.is_(None), RemoteFile.filename != filename).limit(5)))


def margin_for(total_card: int | None) -> int:
    return max(SPACE_MARGIN_MIN, int((total_card or 0) * SPACE_MARGIN_RATIO))


async def build_plan(writer: RemoteWriter, s: Session, staging: StagingStore,
                     requests: list[tuple[str, str | None]], card_total: int | None) -> Plan:
    platform_rows = {p.directory: p for p in s.scalars(select(Platform).where(Platform.present))}
    existing = {d for d, p in platform_rows.items() if not p.is_symlink and d not in FORBIDDEN_TARGETS}
    if not existing:  # catalogue jamais synchronisé : on s'appuie sur les dossiers usuels
        existing = set(KNOWN_EXTENSIONS)
    stats = extension_stats(s)
    listings: dict[str, dict[str, int | None]] = {}
    items: list[PlanItem] = []
    seen_targets: dict[tuple[str, str], str] = {}

    for upload_id, platform in requests:
        up = staging.get(upload_id)
        ext = extension_of(up.filename)
        suggested, choices = suggest_platform(ext, stats, existing)
        platform = platform or suggested
        info = lookup(platform) if platform else None
        item = PlanItem(upload_id, up.filename, up.size, platform, info.label if info else None, choices)
        items.append(item)
        try:
            validate_filename(up.filename)
        except errors.AppError as exc:
            item.error = {"code": exc.code, "message": exc.message}
            continue
        if not platform:
            item.error = {"code": "platform_required",
                          "message": "Choisis la console de destination" + (" : ce format sert à plusieurs consoles" if choices else "")}
            continue
        try:
            ppath = await writer.platform_dir(platform)
        except errors.AppError as exc:
            item.error = {"code": exc.code, "message": exc.message}
            continue
        if platform not in listings:
            listings[platform] = await writer.names_in(ppath)
        names = listings[platform]
        lower = {n.lower(): n for n in names}
        if up.filename in names:
            remote = names[up.filename]
            item.conflict = {"existing": up.filename, "existing_size": remote, "same_size": remote == up.size}
        elif up.filename.lower() in lower:
            # exFAT/FAT ignorent la casse : « Mario.smc » et « mario.smc » désignent le même fichier.
            other = lower[up.filename.lower()]
            item.conflict = {"existing": other, "existing_size": names[other], "same_size": names[other] == up.size,
                             "case_only": True}
        key = (platform, up.filename.lower())
        if key in seen_targets:
            item.error = {"code": "duplicate_in_batch", "message": f"Envoyé deux fois dans ce lot ({seen_targets[key]})"}
            continue
        seen_targets[key] = up.filename
        allowed = allowed_extensions(platform, stats)
        if ext not in allowed:
            item.warnings.append({"code": "format_unusual",
                                  "message": f"Format .{ext or '?'} inhabituel pour cette console"
                                             + (f" (habituels : {', '.join('.' + e for e in sorted(allowed)[:6])})" if allowed else "")})
        same = same_title_files(s, platform, up.filename)
        if same and not item.conflict:
            item.warnings.append({"code": "same_title", "message": "Un jeu au même titre est déjà sur la carte",
                                  "files": same})

    total = sum(i.size for i in items if not i.blocking)
    free = await writer.free_bytes()
    margin = margin_for(card_total)
    fits = None if free is None else total + margin <= free
    return Plan(items, total, free, margin, fits)
