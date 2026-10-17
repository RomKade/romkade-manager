/** État de la bibliothèque, stocké dans l'URL pour que les filtres survivent au retour arrière et aux liens. */
export type Sort = "name" | "size" | "date" | "added";
export type View = "grid" | "table";
export type Art = "box" | "card";

export type LibraryState = {
  q: string;
  platform: string[];
  extension: string[];
  region: string[];
  genre: string[];
  /** Sous-genres (« sport.golf ») du genre choisi. */
  sub: string[];
  /** « Tous les jeux » choisi sur l'accueil : liste complète au lieu du choix de console. */
  all: boolean;
  sort: Sort;
  order: "asc" | "desc";
  view: View;
  /** Jaquettes (banque libretro) ou images du dossier Imgs de la carte. */
  art: Art;
  removed: boolean;
};

const SORTS: Sort[] = ["name", "size", "date", "added"];

/** Ordre naturel de chaque tri : A→Z, gros fichiers d'abord, récents d'abord. */
export const DEFAULT_ORDER: Record<Sort, "asc" | "desc"> = { name: "asc", size: "desc", date: "desc", added: "desc" };

export function parseLibrary(sp: URLSearchParams): LibraryState {
  const sort = (SORTS as string[]).includes(sp.get("sort") ?? "") ? (sp.get("sort") as Sort) : "name";
  const order = sp.get("order") === "asc" || sp.get("order") === "desc" ? (sp.get("order") as "asc" | "desc") : DEFAULT_ORDER[sort];
  return {
    q: sp.get("q") ?? "",
    platform: sp.getAll("platform"),
    extension: sp.getAll("extension"),
    region: sp.getAll("region"),
    genre: sp.getAll("genre"),
    sub: sp.getAll("sub"),
    all: sp.get("all") === "1",
    sort,
    order,
    view: sp.get("view") === "table" ? "table" : "grid",
    art: sp.get("art") === "card" ? "card" : "box",
    removed: sp.get("removed") === "1",
  };
}

export function serializeLibrary(s: LibraryState): URLSearchParams {
  const sp = new URLSearchParams();
  if (s.q) sp.set("q", s.q);
  s.platform.forEach((p) => sp.append("platform", p));
  s.extension.forEach((e) => sp.append("extension", e));
  s.region.forEach((r) => sp.append("region", r));
  s.genre.forEach((g) => sp.append("genre", g));
  s.sub.forEach((g) => sp.append("sub", g));
  if (s.all) sp.set("all", "1");
  if (s.sort !== "name") sp.set("sort", s.sort);
  if (s.order !== DEFAULT_ORDER[s.sort]) sp.set("order", s.order);
  if (s.view !== "grid") sp.set("view", s.view);
  if (s.art !== "box") sp.set("art", s.art);
  if (s.removed) sp.set("removed", "1");
  return sp;
}

/** Paramètres envoyés à GET /api/games (la vue n'en fait pas partie). */
export function toApiQuery(s: LibraryState) {
  return {
    q: s.q.trim() || undefined,
    platform: s.platform,
    extension: s.extension,
    region: s.region,
    genre: s.genre,
    subgenre: s.sub,
    sort: s.sort,
    order: s.order,
    include_removed: s.removed || undefined,
  };
}

/** La console choisie sur l'accueil n'est pas un filtre : elle délimite la page. */
export function activeFilterCount(s: LibraryState): number {
  const platforms = s.platform.length === 1 ? 0 : s.platform.length;
  return platforms + s.extension.length + s.region.length + s.genre.length + s.sub.length + (s.q ? 1 : 0) + (s.removed ? 1 : 0);
}

/** Sans console, sans recherche ni filtre : l'accueil propose de choisir une console. */
export function showsConsolePicker(s: LibraryState): boolean {
  return !s.all && !s.q && s.platform.length + s.extension.length + s.region.length + s.genre.length === 0 && !s.removed;
}

/** Une console ouverte, sans genre choisi, ni recherche ni filtre : on propose de choisir un genre. */
export function showsGenrePicker(s: LibraryState): boolean {
  return s.platform.length === 1 && !s.all && !s.q && s.genre.length + s.extension.length + s.region.length === 0 && !s.removed;
}

/** Ce que garde « Effacer les filtres » : la console ouverte et l'affichage ; on reste sur la liste des jeux. */
export function clearedFilters(s: LibraryState): LibraryState {
  return {
    ...parseLibrary(new URLSearchParams()),
    platform: s.platform.length === 1 ? s.platform : [],
    all: true,
    view: s.view,
    art: s.art,
  };
}
