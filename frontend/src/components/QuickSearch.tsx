import { Search } from "lucide-react";
import { useEffect, useId, useState, type KeyboardEvent, type MouseEvent } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { useFacets, usePlatforms, useQuickSearch } from "../api/queries";
import { regionLabel, useT } from "../i18n";
import { consoleShortName } from "../lib/consoleGroups";
import { genreIcon } from "../lib/genreIcons";
import { useDebounced } from "../lib/hooks";
import { ConsoleBadge } from "./ConsoleBadge";
import { ConsoleIcon } from "./ConsoleIcon";
import { Cover } from "./Cover";

const MAX_SUGGESTIONS = 3;

/** Minuscules, sans accents : « Réflexion » et « reflexion » se valent. */
const fold = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** Un mot du libellé commence par la recherche (« sport », « spo », « advance » pour Game Boy Advance). */
const matches = (q: string, ...labels: (string | null | undefined)[]) =>
  labels.some((l) => l && fold(l).split(/[\s'’-]+/).some((w) => w.startsWith(q)));

type Suggestion =
  | { kind: "genre"; value: string; label: string; count: number }
  | { kind: "console"; value: string; code: string; label: string; count: number };

/**
 * La recherche de l'application, dans la barre du haut de toutes les pages : genres et consoles proposés en tête
 * (« sport », « gba »), puis les jeux (Typesense : fautes de frappe tolérées). Flèches pour choisir, Entrée pour
 * ouvrir le choix ou tous les résultats dans la bibliothèque.
 * Les suggestions sont les mêmes sur toutes les pages. Dans la bibliothèque, la saisie filtre en plus la liste
 * affichée (paramètre « q » de l'adresse, console et filtres gardés) ; Entrée ferme alors les suggestions.
 */
export function QuickSearch({ onOpen }: { onOpen: (id: number) => void }) {
  const t = useT();
  const navigate = useNavigate();
  const onLibrary = useLocation().pathname === "/bibliotheque";
  const [sp, setSp] = useSearchParams();
  const urlQ = onLibrary ? sp.get("q") ?? "" : "";
  const listId = useId();
  const [q, setQ] = useState(urlQ);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const debounced = useDebounced(q, onLibrary ? 180 : 120);
  const res = useQuickSearch(debounced);
  const facets = useFacets([]);
  const platforms = usePlatforms();
  const items = debounced.trim() ? res.data?.items ?? [] : [];
  const total = onLibrary ? 0 : res.data?.total ?? 0;

  // Bibliothèque : l'adresse a changé sans la saisie (retour arrière, filtres effacés, autre page) -> le champ suit.
  useEffect(() => { if (onLibrary) setQ(urlQ); }, [onLibrary, urlQ]);
  // Bibliothèque : la saisie filtre la liste.
  useEffect(() => {
    if (!onLibrary || debounced.trim() === urlQ) return;
    setSp((prev) => {
      const next = new URLSearchParams(prev);
      if (debounced.trim()) next.set("q", debounced.trim()); else next.delete("q");
      return next;
    }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);
  const showAll = () => navigate(`/bibliotheque?q=${encodeURIComponent(q.trim())}&all=1`);

  const needle = fold(debounced.trim());
  const suggestions: Suggestion[] = needle.length < 2 ? [] : [
    ...(facets.data?.genres ?? [])
      .filter((g) => g.count > 0 && matches(needle, t(`common.genre.${g.value}`), g.value))
      .slice(0, MAX_SUGGESTIONS)
      .map((g) => ({ kind: "genre" as const, value: g.value, label: t(`common.genre.${g.value}`), count: g.count })),
    ...(platforms.data ?? [])
      .filter((p) => p.game_count > 0 && matches(needle, p.label, p.directory, p.code, consoleShortName(p.code)))
      .slice(0, MAX_SUGGESTIONS)
      .map((p) => ({ kind: "console" as const, value: p.directory, code: p.code, label: p.label ?? p.directory, count: p.game_count })),
  ];

  const count = suggestions.length + items.length;
  const pick = (i: number) => {
    const s = suggestions[i];
    if (s) navigate(s.kind === "genre" ? `/bibliotheque?genre=${encodeURIComponent(s.value)}&all=1`
      : `/bibliotheque?platform=${encodeURIComponent(s.value)}`);
    else onOpen(items[i - suggestions.length]!.id);
    setOpen(false);
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(count - 1, a + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(-1, a - 1)); }
    else if (e.key === "Escape") { setOpen(false); setActive(-1); }
    else if (e.key === "Enter" && q.trim()) {
      e.preventDefault();
      if (active >= 0 && active < count) pick(active); else if (onLibrary) setOpen(false); else showAll();
    }
  };

  const option = (i: number) => ({
    id: `${listId}-${i}`, role: "option", "aria-selected": i === active,
    className: `quick-search__item ${i === active ? "is-active" : ""}`,
    onMouseDown: (e: MouseEvent) => e.preventDefault(), onMouseEnter: () => setActive(i), onClick: () => pick(i),
  });

  return (
    <div className="quick-search" onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false); }}>
      <label className="search search--top">
        <Search size={18} aria-hidden />
        <span className="visually-hidden">{t("dashboard.searchLabel")}</span>
        <input type="search" role="combobox" aria-expanded={open && count > 0} aria-controls={listId}
          aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined} aria-autocomplete="list"
          placeholder={t("dashboard.searchPlaceholder")} value={q} autoComplete="off"
          onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(-1); }}
          onFocus={() => setOpen(true)} onKeyDown={onKey} />
      </label>
      {open && debounced.trim() && (
        <div className="quick-search__panel">
          {count === 0 ? (
            <p className="muted quick-search__empty">{res.isFetching ? t("common.loading") : t("dashboard.searchNone")}</p>
          ) : (
            <ul id={listId} role="listbox" className="quick-search__list">
              {suggestions.map((s, i) => {
                const Icon = s.kind === "genre" ? genreIcon(s.value) : null;
                return (
                  <li key={`${s.kind}-${s.value}`} {...option(i)}>
                    <span className="quick-search__symbol" aria-hidden>
                      {s.kind === "genre" && Icon ? <Icon size={22} /> : s.kind === "console" && <ConsoleIcon code={s.code} className="quick-search__console" />}
                    </span>
                    <span className="quick-search__text">
                      <span className="quick-search__title">{s.label}</span>
                      <span className="muted">
                        {t(s.kind === "genre" ? "dashboard.searchGenre" : "dashboard.searchConsole", { count: s.count })}
                      </span>
                    </span>
                  </li>
                );
              })}
              {items.map((g, n) => (
                <li key={g.id} {...option(suggestions.length + n)}>
                  <Cover game={g} className="quick-search__cover" />
                  <span className="quick-search__text">
                    <span className="quick-search__title">{g.title}</span>
                    <span className="muted quick-search__meta">
                      <ConsoleBadge code={g.platform.code} label={g.platform.label} />
                      {[g.genre ? t(`common.genre.${g.genre}`) : null, regionLabel(g.region)].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
          {total > 0 && (
            <button type="button" className="quick-search__all" onMouseDown={(e) => e.preventDefault()} onClick={showAll}>
              {t("dashboard.searchAll", { count: total })}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
