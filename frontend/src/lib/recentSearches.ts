import { useCallback, useState } from "react";

/** Dernières recherches de la barre du haut, gardées dans ce navigateur (la plus récente en tête). */
const STORAGE_KEY = "agm-recent-searches";
export const MAX_RECENT_SEARCHES = 6;

function read(): string[] {
  try {
    const list: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    return Array.isArray(list) ? list.filter((s): s is string => typeof s === "string").slice(0, MAX_RECENT_SEARCHES) : [];
  } catch {
    return [];
  }
}

function write(list: string[]): void {
  try {
    if (list.length) localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* stockage indisponible */
  }
}

/** Une recherche déjà présente (sans tenir compte de la casse) remonte en tête au lieu d'apparaître deux fois. */
export function useRecentSearches() {
  const [list, setList] = useState(read);
  const update = useCallback((next: (prev: string[]) => string[]) => setList((prev) => {
    const value = next(prev);
    write(value);
    return value;
  }), []);
  const add = useCallback((term: string) => {
    const q = term.trim();
    if (q) update((prev) => [q, ...prev.filter((s) => s.toLowerCase() !== q.toLowerCase())].slice(0, MAX_RECENT_SEARCHES));
  }, [update]);
  const remove = useCallback((term: string) => update((prev) => prev.filter((s) => s !== term)), [update]);
  const clear = useCallback(() => update(() => []), [update]);
  return { list, add, remove, clear };
}
