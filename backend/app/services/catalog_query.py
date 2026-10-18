"""Lectures du catalogue SQLite (aucun accès à la console)."""

from collections import defaultdict
from typing import Literal

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app import errors
from app.catalog_schemas import (
    CatalogPlatformOut, CatalogStatusOut, ChangeItemOut, ChangeOut, ChangesPageOut, DuplicateGroupOut,
    FacetsOut, FacetValue,
    GameDetailOut, GameOut, GamesPageOut, PlatformRef, ScanRunOut, UnmatchedImagesOut,
)
from app.db.models import Device, Favorite, GameText, Platform, PlatformImage, RemoteFile, ScanChange, ScanRun
from app.device.paths import safe_join
from app.schemas import Page
from app.services.classify import display_title, search_key
from app.services.boxart import has_source as has_boxart_source
from app.services import videos
from app.services.genres import GENRES, UNCLASSIFIED
from app.services.subgenres import LABELS as SUB_LABELS
from app.services.subgenres import ORDER as SUB_ORDER

GAME_KINDS_EXCLUDED = ("apps", "ports")


def to_game(f: RemoteFile) -> GameOut:
    return GameOut(
        id=f.id, platform=PlatformRef.model_validate(f.platform),
        title=display_title(f.full_title) if f.full_title else f.title, full_title=f.full_title,
        normalized_title=f.normalized_title, filename=f.filename, relative_path=f.relative_path,
        extension=f.extension, region=f.region, size=f.size, modified_at=f.mtime, role=f.role,
        has_image=f.image_relpath is not None,
        image_url=f"/api/games/{f.id}/image" if f.image_relpath else None,
        boxart_url=f"/api/games/{f.id}/boxart" if has_boxart_source(f.platform.directory) else None,
        metadata_status=f.metadata_status, genre=f.genre, genre_label=GENRES.get(f.genre) if f.genre else None,
        genre_detail=f.genre_detail, subgenre=f.subgenre, subgenre_label=SUB_LABELS.get(f.subgenre or ""),
        release_year=f.release_year, developer=f.developer, publisher=f.publisher,
        first_seen_at=f.first_seen_at, last_seen_at=f.last_seen_at,
        present=f.deleted_at is None,
        youtube_url=videos.youtube_search_url(videos.build_query(f)),
    )


def list_platforms(s: Session, include_absent: bool = False) -> list[CatalogPlatformOut]:
    active = RemoteFile.deleted_at.is_(None)
    file_stats = dict((r[0], r[1:]) for r in s.execute(
        select(RemoteFile.platform_id,
               func.sum(case((RemoteFile.role == "candidate", 1), else_=0)),
               func.count(RemoteFile.id),
               func.coalesce(func.sum(RemoteFile.size), 0))
        .where(active).group_by(RemoteFile.platform_id)))
    img_stats = dict((r[0], r[1:]) for r in s.execute(
        select(PlatformImage.platform_id, func.count(PlatformImage.id),
               func.sum(case((PlatformImage.matched, 1), else_=0)))
        .group_by(PlatformImage.platform_id)))
    q = select(Platform).order_by(func.lower(Platform.directory))
    if not include_absent:
        q = q.where(Platform.present)
    out = []
    for p in s.scalars(q):
        games, files, size = file_stats.get(p.id, (0, 0, 0))
        imgs, matched = img_stats.get(p.id, (0, 0))
        if p.kind in GAME_KINDS_EXCLUDED:
            games = 0
        out.append(CatalogPlatformOut(
            id=p.id, directory=p.directory, code=p.code, label=p.label, label_status=p.label_status, kind=p.kind,
            present=p.present, image_dir_present=p.image_dir_present, last_scanned_at=p.last_scanned_at,
            game_count=games or 0, file_count=files or 0, total_bytes=size or 0,
            image_count=imgs or 0, images_matched=matched or 0))
    return out


SortKey = Literal["name", "size", "date", "added", "year"]


def search_games(s: Session, *, q: str | None, platforms: list[str] | None, extensions: list[str] | None,
                 regions: list[str] | None, role: str, genres: list[str] | None = None, subgenres: list[str] | None = None,
                 has_image: bool | None, include_removed: bool, favorite: bool = False, console: str | None = None,
                 sort: SortKey, order: Literal["asc", "desc"], offset: int, limit: int) -> GamesPageOut:
    conds = []
    if role != "all":
        conds.append(RemoteFile.role == role)
    if role == "candidate":
        conds.append(Platform.kind.not_in(GAME_KINDS_EXCLUDED))
    if not include_removed:
        conds.append(RemoteFile.deleted_at.is_(None))
    if platforms:
        conds.append(Platform.directory.in_(platforms))
    if extensions:
        conds.append(RemoteFile.extension.in_([e.lower().lstrip(".") for e in extensions]))
    if regions:
        conds.append(or_(*[RemoteFile.region.like(f"%{r}%") for r in regions]))
    if genres:
        known = [g for g in genres if g != UNCLASSIFIED]
        alts = [RemoteFile.genre.in_(known)] if known else []
        if UNCLASSIFIED in genres:
            alts.append(RemoteFile.genre.is_(None))
        conds.append(or_(*alts))
    if subgenres:
        conds.append(RemoteFile.subgenre.in_(subgenres))
    if has_image is not None:
        conds.append(RemoteFile.image_relpath.is_not(None) if has_image else RemoteFile.image_relpath.is_(None))
    if favorite:
        conds.append(RemoteFile.id.in_(select(Favorite.file_id).where(_console_scope(console))))
    if q:
        for word in search_key(q).split():
            conds.append(RemoteFile.search_key.like(f"%{word}%", escape="\\"))

    base = select(RemoteFile).join(Platform).where(and_(*conds))
    total = s.scalar(select(func.count()).select_from(base.subquery()))
    col = {"name": RemoteFile.normalized_title, "size": RemoteFile.size, "date": RemoteFile.mtime,
           "added": RemoteFile.first_seen_at, "year": RemoteFile.release_year}[sort]
    ordering = [col.desc() if order == "desc" else col.asc(), RemoteFile.filename.asc()]
    if sort == "year":  # jeux sans année connue à la fin, puis A→Z dans une même année
        ordering = [col.is_(None), ordering[0], RemoteFile.normalized_title.asc(), RemoteFile.filename.asc()]
    rows = s.scalars(base.options(joinedload(RemoteFile.platform)).order_by(*ordering).offset(offset).limit(limit))
    return GamesPageOut(page=Page(total=total, offset=offset, limit=limit), items=[to_game(r) for r in rows])


def games_by_ids(s: Session, ids: list[int], total: int, offset: int, limit: int) -> GamesPageOut:
    """Page de résultats dans l'ordre donné par le moteur de recherche."""
    rows = {f.id: f for f in s.scalars(select(RemoteFile).options(joinedload(RemoteFile.platform))
                                         .where(RemoteFile.id.in_(ids)))}
    return GamesPageOut(page=Page(total=total, offset=offset, limit=limit),
                        items=[to_game(rows[i]) for i in ids if i in rows])


def _console_scope(console: str | None):
    """Favoris de cette console, plus ceux d'avant la distinction par console (NULL)."""
    return or_(Favorite.console == console, Favorite.console.is_(None))


def favorites(s: Session, console: str | None, limit: int | None = None) -> list[GameOut]:
    """Favoris de la console branchée présents sur sa carte, le dernier ajouté en tête. Ceux d'une autre console
    (ou disparus de la carte) restent en base et reviennent quand on la rebranche."""
    q = (select(RemoteFile).join(Favorite, Favorite.file_id == RemoteFile.id).options(joinedload(RemoteFile.platform))
         .where(_console_scope(console), RemoteFile.deleted_at.is_(None))
         .group_by(RemoteFile.id).order_by(func.max(Favorite.created_at).desc(), func.max(Favorite.id).desc()))
    return [to_game(f) for f in s.scalars(q.limit(limit) if limit else q).unique()]


def is_favorite(s: Session, console: str | None, file_id: int) -> bool:
    return s.scalar(select(Favorite.id).where(Favorite.file_id == file_id, _console_scope(console)).limit(1)) is not None


def set_favorite(s: Session, console: str | None, file_id: int, on: bool) -> None:
    get_file(s, file_id)
    rows = s.scalars(select(Favorite).where(Favorite.file_id == file_id, _console_scope(console))).all()
    if on and not rows:
        s.add(Favorite(file_id=file_id, console=console))
    elif not on:
        for row in rows:
            s.delete(row)


def get_file(s: Session, file_id: int) -> RemoteFile:
    f = s.get(RemoteFile, file_id, options=[joinedload(RemoteFile.platform)])
    if f is None:
        raise errors.AppError("game_not_found", "Jeu introuvable dans le catalogue", 404, {"id": file_id})
    return f


def game_detail(s: Session, file_id: int, roms_root: str, console: str | None = None) -> GameDetailOut:
    f = get_file(s, file_id)
    dups = s.scalars(select(RemoteFile).options(joinedload(RemoteFile.platform)).where(
        RemoteFile.platform_id == f.platform_id, RemoteFile.normalized_title == f.normalized_title,
        RemoteFile.id != f.id, RemoteFile.role == "candidate", RemoteFile.deleted_at.is_(None)))
    hist = s.execute(select(ScanChange, ScanRun.started_at).join(ScanRun, ScanChange.scan_run_id == ScanRun.id)
                     .where(ScanChange.remote_file_id == f.id).order_by(ScanChange.id.desc()).limit(50))
    return GameDetailOut(
        **to_game(f).model_dump(),
        release_date=f.release_date, franchise=f.franchise, description=f.description, info_url=f.info_url,
        descriptions={t.lang: {"text": t.text, "origin": t.origin} for t in s.scalars(select(GameText).where(
            GameText.platform_id == f.platform_id, GameText.normalized_title == f.normalized_title))},
        favorite=is_favorite(s, console, f.id),
        remote_path=safe_join(roms_root, f.platform.directory, f.relative_path),
        image_relpath=f.image_relpath,
        possible_duplicates=[to_game(d) for d in dups] if f.role == "candidate" else [],
        history=[ChangeOut(scan_run_id=c.scan_run_id, change=c.change, old_size=c.old_size, new_size=c.new_size,
                           old_mtime=c.old_mtime, new_mtime=c.new_mtime, run_started_at=started)
                 for c, started in hist],
    )


def status(s: Session, sync_running: bool) -> CatalogStatusOut:
    last = s.scalar(select(ScanRun).order_by(ScanRun.id.desc()).limit(1))
    last_ok = s.scalar(select(func.max(ScanRun.finished_at)).where(ScanRun.status.in_(("completed", "partial"))))
    plats = list_platforms(s)
    dev = s.get(Device, 1)
    return CatalogStatusOut(
        synced=last_ok is not None, sync_running=sync_running,
        last_run=ScanRunOut.model_validate(last) if last else None,
        last_successful_sync_at=last_ok,
        platform_count=sum(1 for p in plats if p.game_count > 0),  # consoles ayant au moins un jeu
        game_count=sum(p.game_count for p in plats),
        file_count=sum(p.file_count for p in plats),
        total_bytes=sum(p.total_bytes for p in plats),
        storage_total_bytes=dev.total_bytes if dev else None,
        storage_free_bytes=dev.free_bytes if dev else None,
        storage_measured_at=dev.storage_measured_at if dev else None,
    )


def get_run(s: Session, run_id: int) -> ScanRunOut:
    run = s.get(ScanRun, run_id)
    if run is None:
        raise errors.AppError("sync_not_found", "Synchronisation introuvable", 404, {"id": run_id})
    return ScanRunOut.model_validate(run)


def list_runs(s: Session, limit: int) -> list[ScanRunOut]:
    return [ScanRunOut.model_validate(r) for r in s.scalars(select(ScanRun).order_by(ScanRun.id.desc()).limit(limit))]


def changes(s: Session, run_id: int | None, change: str | None, offset: int, limit: int) -> ChangesPageOut:
    if run_id is None:
        run_id = s.scalar(select(func.max(ScanRun.id)).where(ScanRun.status.in_(("completed", "partial"))))
    conds = [ScanChange.scan_run_id == run_id]
    if change:
        conds.append(ScanChange.change == change)
    total = s.scalar(select(func.count(ScanChange.id)).where(*conds)) or 0
    rows = s.execute(select(ScanChange, ScanRun.started_at, RemoteFile).select_from(ScanChange)
                     .join(ScanRun, ScanChange.scan_run_id == ScanRun.id)
                     .join(RemoteFile, ScanChange.remote_file_id == RemoteFile.id)
                     .options(joinedload(RemoteFile.platform)).where(*conds)
                     .order_by(ScanChange.id).offset(offset).limit(limit))
    items = [ChangeItemOut(scan_run_id=c.scan_run_id, change=c.change, old_size=c.old_size, new_size=c.new_size,
                           old_mtime=c.old_mtime, new_mtime=c.new_mtime, run_started_at=started, game=to_game(f))
             for c, started, f in rows]
    return ChangesPageOut(page=Page(total=total, offset=offset, limit=limit), items=items)


def duplicates(s: Session, platforms: list[str] | None) -> list[DuplicateGroupOut]:
    conds = [RemoteFile.role == "candidate", RemoteFile.deleted_at.is_(None), RemoteFile.normalized_title != "",
             Platform.kind.not_in(GAME_KINDS_EXCLUDED)]
    if platforms:
        conds.append(Platform.directory.in_(platforms))
    keys = s.execute(select(RemoteFile.platform_id, RemoteFile.normalized_title).join(Platform).where(*conds)
                     .group_by(RemoteFile.platform_id, RemoteFile.normalized_title)
                     .having(func.count(RemoteFile.id) > 1)).all()
    if not keys:
        return []
    wanted = {(p, t) for p, t in keys}
    rows = s.scalars(select(RemoteFile).join(Platform).options(joinedload(RemoteFile.platform)).where(
        *conds, RemoteFile.platform_id.in_({p for p, _ in keys}),
        RemoteFile.normalized_title.in_({t for _, t in keys})))
    groups: dict[tuple[int, str], list[RemoteFile]] = defaultdict(list)
    for r in rows:
        if (r.platform_id, r.normalized_title) in wanted:
            groups[(r.platform_id, r.normalized_title)].append(r)
    out = []
    for (_, title), files in sorted(groups.items(), key=lambda kv: (kv[1][0].platform.directory, kv[0][1])):
        sizes = [f.size for f in files]
        same_size = len(sizes) != len(set(sizes))
        out.append(DuplicateGroupOut(
            platform=PlatformRef.model_validate(files[0].platform), normalized_title=title,
            confidence="likely" if same_size else "possible",
            reason="même titre et même taille, à vérifier (éditions différentes possibles)" if same_size
            else "même titre, régions ou versions différentes",
            items=[to_game(f) for f in sorted(files, key=lambda f: f.filename)]))
    return out


def unmatched_images(s: Session, sample: int) -> list[UnmatchedImagesOut]:
    out = []
    for p in s.scalars(select(Platform).where(Platform.present).order_by(Platform.directory)):
        q = select(PlatformImage.filename).where(PlatformImage.platform_id == p.id, PlatformImage.matched.is_(False))
        total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
        if total:
            out.append(UnmatchedImagesOut(platform=PlatformRef.model_validate(p), total=total,
                                          sample=list(s.scalars(q.order_by(PlatformImage.filename).limit(sample)))))
    return out


def facets(s: Session, platforms: list[str] | None) -> FacetsOut:
    conds = [RemoteFile.role == "candidate", RemoteFile.deleted_at.is_(None), Platform.kind.not_in(GAME_KINDS_EXCLUDED)]
    if platforms:
        conds.append(Platform.directory.in_(platforms))
    ext_rows = s.execute(select(RemoteFile.extension, func.count(RemoteFile.id)).join(Platform).where(
        *conds, RemoteFile.extension.is_not(None)).group_by(RemoteFile.extension)
        .order_by(func.count(RemoteFile.id).desc()))
    region_counts: dict[str, int] = defaultdict(int)
    for (regions,) in s.execute(select(RemoteFile.region).join(Platform).where(*conds, RemoteFile.region.is_not(None))):
        for r in regions.split(", "):
            region_counts[r] += 1
    genre_counts = dict(s.execute(select(RemoteFile.genre, func.count(RemoteFile.id)).join(Platform).where(*conds)
                                  .group_by(RemoteFile.genre)).all())
    order = list(GENRES)
    genre_values = [FacetValue(value=g, label=GENRES[g], count=c)
                    for g, c in sorted(((g, c) for g, c in genre_counts.items() if g in GENRES), key=lambda kv: order.index(kv[0]))]
    if genre_counts.get(None):
        genre_values.append(FacetValue(value=UNCLASSIFIED, label="Non classé", count=genre_counts[None]))
    sub_counts = dict(s.execute(select(RemoteFile.subgenre, func.count(RemoteFile.id)).join(Platform)
                                .where(*conds, RemoteFile.subgenre.is_not(None)).group_by(RemoteFile.subgenre)).all())
    sub_values = [FacetValue(value=k, label=SUB_LABELS[k], count=sub_counts[k]) for k in SUB_ORDER if sub_counts.get(k)]
    return FacetsOut(
        extensions=[FacetValue(value=e, count=c) for e, c in ext_rows],
        regions=[FacetValue(value=r, count=c) for r, c in sorted(region_counts.items(), key=lambda kv: -kv[1])],
        genres=genre_values,
        subgenres=sub_values,
    )
