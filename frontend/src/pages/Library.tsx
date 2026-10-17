import * as ToggleGroup from "@radix-ui/react-toggle-group";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowLeft, ArrowUp, ChevronRight, LayoutGrid, LibraryBig, Play, Plus, Rows3, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import type { CatalogPlatform, Facets, Game } from "../api/client";
import { useFacets, useGamesInfinite, usePlatforms, useStatus } from "../api/queries";
import { ConsoleBadge } from "../components/ConsoleBadge";
import { ConsoleIcon } from "../components/ConsoleIcon";
import { Cover } from "../components/Cover";
import { MultiFilter, SelectField } from "../components/Filters";
import { GameSheet } from "../components/GameSheet";
import { Empty, ErrorNotice, Spinner } from "../components/ui";
import { VideoDialog } from "../components/VideoDialog";
import { regionLabel, useT } from "../i18n";
import { bytes, date } from "../lib/format";
import { useWidth } from "../lib/hooks";
import { CONSOLE_GROUPS, groupOf, OTHER_GROUP } from "../lib/consoleGroups";
import { genreIcon } from "../lib/genreIcons";
import {
  activeFilterCount, clearedFilters, DEFAULT_ORDER, parseLibrary, serializeLibrary, showsConsolePicker, showsGenrePicker,
  toApiQuery,
  type Art, type LibraryState, type Sort,
} from "../lib/libraryParams";

const SORT_OPTIONS = [
  { value: "name", label: "library.sort.name" },
  { value: "added", label: "library.sort.added" },
  { value: "date", label: "library.sort.date" },
  { value: "size", label: "library.sort.size" },
];

export function LibraryPage() {
  const t = useT();
  const [sp, setSp] = useSearchParams();
  const state = useMemo(() => parseLibrary(sp), [sp]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [videoGame, setVideoGame] = useState<Game | null>(null);
  const status = useStatus();

  const update = (patch: Partial<LibraryState>) => setSp(serializeLibrary({ ...state, ...patch }), { replace: true });
  /** Changer de console ou revenir à l'accueil crée une entrée d'historique : le retour arrière y ramène. */
  const navigate = (next: LibraryState) => setSp(serializeLibrary(next));

  // Trois étapes : choix de la console, puis du genre, puis la liste des jeux.
  // La recherche (barre du haut) écrit « q » dans l'adresse.
  const step = showsConsolePicker(state) ? "consoles" : showsGenrePicker(state) ? "genres" : "games";
  const picker = step !== "games";
  const platforms = usePlatforms();
  const facets = useFacets(state.platform);
  const games = useGamesInfinite(toApiQuery(state), !picker);
  const items = useMemo(() => games.data?.pages.flatMap((p) => p.items) ?? [], [games.data]);
  const total = games.data?.pages[0]?.page.total;

  const libraryPlatforms = (platforms.data ?? []).filter((p) => p.game_count > 0);
  const platformOptions = libraryPlatforms.map((p) => ({ value: p.directory, label: p.label ?? p.directory, count: p.game_count }));
  const extOptions = (facets.data?.extensions ?? []).map((f) => ({ value: f.value, label: `.${f.value}`, count: f.count }));
  const regionOptions = (facets.data?.regions ?? []).map((f) => ({ value: f.value, label: regionLabel(f.value), count: f.count }));
  const genreOptions = (facets.data?.genres ?? []).map((f) => ({ value: f.value, label: t(`common.genre.${f.value}`), count: f.count }));
  const filters = activeFilterCount(state);
  const single = state.platform.length === 1;
  const singleLabel = single
    ? libraryPlatforms.find((p) => p.directory === state.platform[0])?.label ?? state.platform[0]
    : undefined;
  const singleCode = single ? libraryPlatforms.find((p) => p.directory === state.platform[0])?.code ?? state.platform[0]! : "";
  const home = { ...parseLibrary(new URLSearchParams()), view: state.view, art: state.art };
  const consoleHome = { ...home, platform: state.platform };
  const oneGenre = state.genre.length === 1 ? genreOptions.find((g) => g.value === state.genre[0])?.label : undefined;

  const neverSynced = status.data && !status.data.synced;

  return (
    <div className="library">
      <header className="library__bar">
        <div className="library__title">
          {step === "consoles" ? (
            <h1>{t("library.title")}</h1>
          ) : (
            <>
              <nav className="crumbs" aria-label={t("library.crumbs")}>
                <button type="button" className="crumb" onClick={() => navigate(home)}>
                  <ArrowLeft size={16} aria-hidden /> {t("library.crumbs.consoles")}
                </button>
                {step === "games" && single && (
                  <>
                    <ChevronRight size={14} aria-hidden className="crumbs__sep" />
                    <button type="button" className="crumb" onClick={() => navigate(consoleHome)}>{t("library.crumbs.genres")}</button>
                  </>
                )}
              </nav>
              {single && <ConsoleIcon code={singleCode} className="library__icon" />}
              <h1>{singleLabel ?? t("library.allGames")}</h1>
              {step === "games" && oneGenre && <GenrePill genre={state.genre[0]!} />}
            </>
          )}
          <p className="library__count num" aria-live="polite">
            {step === "consoles"
              ? status.data ? t("library.countAll", { games: t("library.games", { count: status.data.game_count }), consoles: t("library.consoleCount", { count: libraryPlatforms.length }) }) : " "
              : step === "genres"
                ? platforms.data ? t("library.games", { count: libraryPlatforms.find((p) => p.directory === state.platform[0])?.game_count ?? 0 }) : " "
                : total == null ? " " : t("library.games", { count: total })}
          </p>
        </div>
        {!picker && (
          <ToggleGroup.Root
            type="single"
            className="segmented"
            value={state.view}
            onValueChange={(v) => v && update({ view: v as LibraryState["view"] })}
            aria-label={t("library.view")}
          >
            <ToggleGroup.Item value="grid" className="segmented__item" aria-label={t("library.view.grid")}>
              <LayoutGrid size={16} aria-hidden />
            </ToggleGroup.Item>
            <ToggleGroup.Item value="table" className="segmented__item" aria-label={t("library.view.table")}>
              <Rows3 size={16} aria-hidden />
            </ToggleGroup.Item>
          </ToggleGroup.Root>
        )}
        <Link to="/ajouter-des-jeux" className="button">
          <Plus size={16} aria-hidden /> {t("library.addGames")}
        </Link>
      </header>

      {!picker && (
        <div className="library__filters" role="toolbar" aria-label={t("library.filters")}>
          {!single && (
            <MultiFilter label={t("library.filter.console")} options={platformOptions} selected={state.platform}
              onChange={(platform) => update({ platform, extension: [], region: [] })} />
          )}
          <MultiFilter label={t("library.filter.genre")} options={genreOptions} selected={state.genre} onChange={(genre) => update({ genre, sub: [] })} />
          <MultiFilter label={t("library.filter.format")} options={extOptions} selected={state.extension} onChange={(extension) => update({ extension })} />
          <MultiFilter label={t("library.filter.region")} options={regionOptions} selected={state.region} onChange={(region) => update({ region })} />
          <span className="library__sep" aria-hidden />
          <SelectField label={t("library.sortBy")} value={state.sort} options={SORT_OPTIONS.map((o) => ({ ...o, label: t(o.label) }))}
            onChange={(v) => update({ sort: v as Sort, order: DEFAULT_ORDER[v as Sort] })} />
          <button type="button" className="chip" onClick={() => update({ order: state.order === "asc" ? "desc" : "asc" })}
            aria-label={state.order === "asc" ? t("library.order.asc") : t("library.order.desc")}>
            {state.order === "asc" ? <ArrowUp size={14} aria-hidden /> : <ArrowDown size={14} aria-hidden />}
          </button>
          <ToggleGroup.Root type="single" className="segmented segmented--text" value={state.art}
            onValueChange={(v) => v && update({ art: v as LibraryState["art"] })} aria-label={t("library.art")}>
            <ToggleGroup.Item value="box" className="segmented__item">{t("library.art.box")}</ToggleGroup.Item>
            <ToggleGroup.Item value="card" className="segmented__item">{t("library.art.card")}</ToggleGroup.Item>
          </ToggleGroup.Root>
          <label className="toggle-inline">
            <input type="checkbox" checked={state.removed} onChange={(e) => update({ removed: e.target.checked })} />
            {t("library.includeRemoved")}
          </label>
          {filters > 0 && (
            <button type="button" className="link-button" onClick={() => navigate(clearedFilters(state))}>
              <X size={14} aria-hidden /> {t("library.clearFilters")}
            </button>
          )}
        </div>
      )}

      {!picker && state.genre.length === 1 && facets.data && (
        <SubgenreChips genre={state.genre[0]!} values={facets.data.subgenres ?? []} selected={state.sub}
          onChange={(sub) => update({ sub })} />
      )}

      <div className="screen">
        {neverSynced ? (
          <Empty title={t("library.empty.title")}>
            <p>{t("library.empty.text")}</p>
            <Link className="button button--primary" to="/synchronisation">{t("library.empty.sync")}</Link>
          </Empty>
        ) : step === "genres" ? (
          facets.isError ? (
            <div className="screen__pad"><ErrorNotice error={facets.error} title={t("library.error.genres")} /></div>
          ) : facets.isPending ? (
            <div className="screen__pad"><Spinner label={t("library.loading.genres")} /></div>
          ) : (
            <GenrePicker genres={facets.data.genres}
              onPick={(g) => navigate({ ...consoleHome, genre: [g] })}
              onAll={() => navigate({ ...consoleHome, all: true })} />
          )
        ) : picker ? (
          platforms.isError ? (
            <div className="screen__pad"><ErrorNotice error={platforms.error} title={t("library.error.consoles")} /></div>
          ) : platforms.isPending ? (
            <div className="screen__pad"><Spinner label={t("library.loading.consoles")} /></div>
          ) : (
            <ConsolePicker platforms={libraryPlatforms} total={status.data?.game_count}
              onPick={(dir) => navigate({ ...home, platform: [dir] })}
              onAll={() => navigate({ ...home, all: true })} />
          )
        ) : games.isError ? (
          <div className="screen__pad"><ErrorNotice error={games.error} title={t("library.error.games")} /></div>
        ) : games.isPending ? (
          <div className="screen__pad"><Spinner label={t("library.loading.games")} /></div>
        ) : items.length === 0 ? (
          <Empty title={t("library.noMatch.title")}>
            <p>{t("library.noMatch.text")}</p>
          </Empty>
        ) : state.view === "grid" ? (
          <CoverGrid items={items} total={total ?? 0} art={state.art} showPlatform={!single} onOpen={setOpenId} onVideo={setVideoGame}
            fetchMore={() => games.hasNextPage && !games.isFetchingNextPage && games.fetchNextPage()} />
        ) : (
          <GameTable items={items} total={total ?? 0} art={state.art} sort={state.sort} order={state.order} onOpen={setOpenId} onVideo={setVideoGame}
            onSort={(sort) => update(sort === state.sort ? { order: state.order === "asc" ? "desc" : "asc" } : { sort, order: DEFAULT_ORDER[sort] })}
            fetchMore={() => games.hasNextPage && !games.isFetchingNextPage && games.fetchNextPage()} />
        )}
      </div>
      <GameSheet id={openId} onClose={() => setOpenId(null)} onOpen={setOpenId} onVideo={setVideoGame} />
      <VideoDialog game={videoGame} onClose={() => setVideoGame(null)} />
    </div>
  );
}

function ConsolePicker({ platforms, total, onPick, onAll }: {
  platforms: CatalogPlatform[]; total: number | undefined; onPick: (dir: string) => void; onAll: () => void;
}) {
  const t = useT();
  const groups = useMemo(() => {
    const by = new Map<string, CatalogPlatform[]>();
    for (const p of [...platforms].sort((a, b) => b.game_count - a.game_count)) {
      const g = groupOf(p.code);
      by.set(g, [...(by.get(g) ?? []), p]);
    }
    return [...CONSOLE_GROUPS.map((g) => g.label), OTHER_GROUP].filter((g) => by.has(g)).map((g) => ({ label: g, items: by.get(g)! }));
  }, [platforms]);

  // Échelle commune à toutes les cartes : on compare les consoles entre elles.
  const maxGames = Math.max(1, ...platforms.map((p) => p.game_count));
  const maxBytes = Math.max(1, ...platforms.map((p) => p.total_bytes));

  if (platforms.length === 0) {
    return <Empty title={t("library.noConsoles.title")}><p>{t("library.noConsoles.text")}</p></Empty>;
  }
  return (
    <div className="console-picker">
      <button type="button" className="console-card console-card--all" onClick={onAll}>
        <LibraryBig size={22} aria-hidden />
        <span className="console-card__name">{t("library.allGames")}</span>
        <span className="console-card__meta num">{total == null ? "" : t("library.allConsolesMeta", { count: total })}</span>
      </button>
      {groups.map((g) => (
        <section key={g.label} className="console-group" aria-label={t(`common.group.${g.label}`)}>
          <h2 className="console-group__title">{t(`common.group.${g.label}`)}</h2>
          <ul className="console-group__list">
            {g.items.map((p) => (
              <li key={p.id}>
                <button type="button" className="console-card" onClick={() => onPick(p.directory)}>
                  <ConsoleIcon code={p.code} className="console-card__icon" />
                  <span className="console-card__code">{p.directory}</span>
                  <span className="console-card__name">{p.label ?? p.directory}</span>
                  <Gauge label={t("library.games", { count: p.game_count })} value={p.game_count} max={maxGames} kind="games" />
                  <Gauge label={bytes(p.total_bytes)} value={p.total_bytes} max={maxBytes} kind="size" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** Jauge d'une carte de console : nombre de jeux ou place occupée, relative à la console la plus fournie. */
function Gauge({ label, value, max, kind }: { label: string; value: number; max: number; kind: "games" | "size" }) {
  const t = useT();
  return (
    <span className={`gauge gauge--${kind}`} title={t(`library.gauge.${kind}`)}>
      <span className="gauge__bar" aria-hidden><span style={{ width: `${Math.max(2, (value / max) * 100)}%` }} /></span>
      <span className="gauge__label num">{label}</span>
    </span>
  );
}

/** Sous-genres du genre choisi (« Sport » -> Football, Golf, Basket…), avec leur nombre de jeux : un clic filtre. */
function SubgenreChips({ genre, values, selected, onChange }: {
  genre: string; values: { value: string; count: number }[]; selected: string[]; onChange: (sub: string[]) => void;
}) {
  const t = useT();
  const mine = values.filter((v) => v.value.startsWith(`${genre}.`));
  if (mine.length < 2) return null;
  const total = mine.reduce((n, v) => n + v.count, 0);
  return (
    <div className="subgenres" role="group" aria-label={t("library.subgenres", { genre: t(`common.genre.${genre}`) })}>
      <button type="button" className={`chip ${selected.length === 0 ? "is-on" : ""}`} aria-pressed={selected.length === 0}
        onClick={() => onChange([])}>
        {t("library.subgenres.all")} <span className="chip__count num">{total}</span>
      </button>
      {mine.map((v) => {
        const on = selected.includes(v.value);
        return (
          <button key={v.value} type="button" className={`chip ${on ? "is-on" : ""}`} aria-pressed={on}
            onClick={() => onChange(on ? [] : [v.value])}>
            {t(`common.subgenre.${v.value}`)} <span className="chip__count num">{v.count}</span>
          </button>
        );
      })}
    </div>
  );
}

function GenrePill({ genre }: { genre: string }) {
  const t = useT();
  const Icon = genreIcon(genre);
  return <span className={`genre-pill genre-card--${genre}`}><Icon size={15} aria-hidden /> {t(`common.genre.${genre}`)}</span>;
}

function GenrePicker({ genres, onPick, onAll }: {
  genres: Facets["genres"]; onPick: (genre: string) => void; onAll: () => void;
}) {
  const t = useT();
  const total = genres.reduce((n, g) => n + g.count, 0);
  if (total === 0) return <Empty title={t("library.noGamesOnConsole")} />;
  return (
    <div className="console-picker">
      <ul className="genre-list" aria-label={t("library.genres")}>
        <li>
          <button type="button" className="genre-card genre-card--all" onClick={onAll}>
            <LibraryBig size={26} aria-hidden className="genre-card__icon" />
            <span className="genre-card__name">{t("library.allGenres")}</span>
            <span className="genre-card__meta num">{t("library.games", { count: total })}</span>
          </button>
        </li>
        {genres.map((g) => {
          const Icon = genreIcon(g.value);
          return (
            <li key={g.value}>
              <button type="button" className={`genre-card genre-card--${g.value}`} onClick={() => onPick(g.value)}>
                <Icon size={26} aria-hidden className="genre-card__icon" />
                <span className="genre-card__name">{t(`common.genre.${g.value}`)}</span>
                <span className="genre-card__meta num">{t("library.games", { count: g.count })}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const TILE_MIN = 164;
const GAP = 14;
const CAPTION = 52;

function CoverGrid({ items, total, art, showPlatform, onOpen, onVideo, fetchMore }: {
  items: Game[]; total: number; art: Art; showPlatform: boolean; onOpen: (id: number) => void; onVideo: (g: Game) => void;
  fetchMore: () => void;
}) {
  const t = useT();
  const [ref, width] = useWidth<HTMLDivElement>();
  const inner = Math.max(0, width - 2 * 20);
  const cols = Math.max(2, Math.floor((inner + GAP) / (TILE_MIN + GAP)));
  const tile = cols > 0 ? (inner - GAP * (cols - 1)) / cols : TILE_MIN;
  const rowCount = Math.ceil(total / cols);
  const rowH = tile + CAPTION + GAP;

  const v = useVirtualizer({ count: rowCount, getScrollElement: () => ref.current, estimateSize: () => rowH, overscan: 3 });
  useEffect(() => v.measure(), [rowH, v]);
  const vItems = v.getVirtualItems();
  const lastRow = vItems[vItems.length - 1]?.index ?? 0;
  useEffect(() => {
    if ((lastRow + 4) * cols >= items.length && items.length < total) fetchMore();
  }, [lastRow, cols, items.length, total, fetchMore]);

  return (
    <div ref={ref} className="grid-scroll" role="list" aria-label={t("library.gamesList")}>
      <div style={{ height: v.getTotalSize(), position: "relative" }}>
        {width > 0 && vItems.map((row) => (
          <div key={row.key} className="grid-row" style={{ transform: `translateY(${row.start}px)`, gridTemplateColumns: `repeat(${cols}, 1fr)`, gap: GAP }}>
            {Array.from({ length: cols }, (_, c) => {
              const g = items[row.index * cols + c];
              if (!g) return row.index * cols + c < total ? <div key={c} className="tile tile--ghost" aria-hidden style={{ height: tile }} /> : null;
              return (
                <div key={g.id} role="listitem" className={`tile ${g.present ? "" : "is-removed"}`}>
                  <button type="button" className="tile__open" onClick={() => onOpen(g.id)}>
                    <Cover key={`${g.id}-${art}`} game={g} art={art} />
                    <span className="tile__title">{g.title}</span>
                    <span className="tile__meta">
                      {showPlatform && <ConsoleBadge code={g.platform.code} label={g.platform.label} />}
                      {[g.genre ? t(`common.genre.${g.genre}`) : null, showPlatform ? null : regionLabel(g.region)].filter(Boolean).join(", ")}
                    </span>
                  </button>
                  <PlayButton game={g} onVideo={onVideo} className="tile__play" />
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

const COLUMNS: { key: string; label: string; sort?: Sort; className?: string }[] = [
  { key: "cover", label: "" },
  { key: "title", label: "library.col.title", sort: "name" },
  { key: "platform", label: "library.col.platform" },
  { key: "genre", label: "library.col.genre" },
  { key: "ext", label: "library.col.ext" },
  { key: "region", label: "library.col.region" },
  { key: "size", label: "library.col.size", sort: "size", className: "num-col" },
  { key: "date", label: "library.col.date", sort: "date" },
  { key: "added", label: "library.col.added", sort: "added" },
];

function GameTable({
  items, total, art, sort, order, onSort, onOpen, onVideo, fetchMore,
}: {
  items: Game[]; total: number; art: Art; sort: Sort; order: "asc" | "desc";
  onSort: (s: Sort) => void; onOpen: (id: number) => void; onVideo: (g: Game) => void; fetchMore: () => void;
}) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({ count: items.length, getScrollElement: () => ref.current, estimateSize: () => 52, overscan: 8 });
  const vItems = v.getVirtualItems();
  const last = vItems[vItems.length - 1]?.index ?? 0;
  useEffect(() => {
    if (last > items.length - 30 && items.length < total) fetchMore();
  }, [last, items.length, total, fetchMore]);
  const pad = vItems[0]?.start ?? 0;
  const padEnd = v.getTotalSize() - (vItems[vItems.length - 1]?.end ?? 0);

  return (
    <div ref={ref} className="table-scroll">
      <table className="games-table">
        <thead>
          <tr>
            {COLUMNS.map((c) => (
              <th key={c.key} scope="col" className={c.className} aria-sort={c.sort === sort ? (order === "asc" ? "ascending" : "descending") : undefined}>
                {c.sort ? (
                  <button type="button" className="th-sort" onClick={() => onSort(c.sort!)}>
                    {t(c.label)}
                    {c.sort === sort && (order === "asc" ? <ArrowUp size={12} aria-hidden /> : <ArrowDown size={12} aria-hidden />)}
                  </button>
                ) : c.label ? t(c.label) : <span className="visually-hidden">{t("library.col.cover")}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {pad > 0 && <tr aria-hidden style={{ height: pad }} />}
          {vItems.map((r) => {
            const g = items[r.index]!;
            return (
              <tr key={g.id} className={g.present ? "" : "is-removed"} onClick={() => onOpen(g.id)}>
                <td className="cell-cover"><Cover key={`${g.id}-${art}`} game={g} art={art} /></td>
                <td>
                  <span className="row-title-line">
                    <button type="button" className="row-title" onClick={(e) => { e.stopPropagation(); onOpen(g.id); }}>{g.title}</button>
                    <PlayButton game={g} onVideo={onVideo} className="row-play" />
                  </span>
                  <span className="row-file">{g.filename}</span>
                </td>
                <td><ConsoleBadge code={g.platform.code} label={g.platform.label} /></td>
                <td>{g.genre ? t(`common.genre.${g.genre}`) : ""}</td>
                <td>{g.extension ? `.${g.extension}` : ""}</td>
                <td>{regionLabel(g.region)}</td>
                <td className="num-col num">{bytes(g.size)}</td>
                <td>{date(g.modified_at)}</td>
                <td>{date(g.first_seen_at)}</td>
              </tr>
            );
          })}
          {padEnd > 0 && <tr aria-hidden style={{ height: padEnd }} />}
        </tbody>
      </table>
    </div>
  );
}

function PlayButton({ game, onVideo, className }: { game: Game; onVideo: (g: Game) => void; className: string }) {
  const t = useT();
  return (
    <button type="button" className={className} aria-label={t("library.trailerFor", { title: game.title })} title={t("library.trailer")}
      onClick={(e) => { e.stopPropagation(); onVideo(game); }}>
      <Play size={14} fill="currentColor" aria-hidden />
    </button>
  );
}
