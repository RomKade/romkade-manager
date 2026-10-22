/**
 * Traductions de l'interface : français (langue de référence), anglais, espagnol.
 *
 * Chaque zone de l'application a son fichier dans locales/ : `export default { fr: {...}, en: {...}, es: {...} }`.
 * Les clés y sont courtes ; on les appelle préfixées par le nom du fichier : t("library.search").
 * Variables : « {name} ». Pluriels : clés `x_one` / `x_other`, choisies avec la variable `count`.
 * Une clé absente dans une langue retombe sur le français, puis sur la clé elle-même.
 */
import account from "./locales/account";
import assistant from "./locales/assistant";
import auth from "./locales/auth";
import bluetooth from "./locales/bluetooth";
import common from "./locales/common";
import dashboard from "./locales/dashboard";
import legal from "./locales/legal";
import library from "./locales/library";
import players from "./locales/players";
import playtime from "./locales/playtime";
import saves from "./locales/saves";
import screenshots from "./locales/screenshots";
import settings from "./locales/settings";
import sheet from "./locales/sheet";
import sync from "./locales/sync";
import transfers from "./locales/transfers";

export type Lang = "fr" | "en" | "es";
export type Messages = Record<Lang, Record<string, string>>;
export const LANGS: { code: Lang; label: string }[] = [
  { code: "fr", label: "Français" },
  { code: "en", label: "English" },
  { code: "es", label: "Español" },
];
const LOCALES: Record<Lang, string> = { fr: "fr-FR", en: "en-GB", es: "es-ES" };
const STORAGE_KEY = "agm-lang";

export const NAMESPACES: Record<string, Messages> = { account, assistant, auth, bluetooth, common, dashboard, legal, library, players, playtime, saves, screenshots, settings, sheet, sync, transfers };

const catalogs: Record<Lang, Record<string, string>> = { fr: {}, en: {}, es: {} };
for (const [ns, messages] of Object.entries(NAMESPACES)) {
  for (const lang of Object.keys(catalogs) as Lang[]) {
    for (const [k, v] of Object.entries(messages[lang] ?? {})) catalogs[lang][`${ns}.${k}`] = v;
  }
}

function detect(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "fr" || saved === "en" || saved === "es") return saved;
  } catch {
    /* stockage indisponible */
  }
  const nav = (typeof navigator !== "undefined" ? navigator.language : "fr").slice(0, 2);
  return nav === "en" || nav === "es" ? nav : "fr";
}

let current: Lang = detect();
const listeners = new Set<() => void>();

export const getLang = () => current;
export const locale = () => LOCALES[current];

export function setLang(lang: Lang): void {
  current = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* stockage indisponible */
  }
  if (typeof document !== "undefined") document.documentElement.lang = lang;
  listeners.forEach((l) => l());
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export type Vars = Record<string, string | number>;

export function has(key: string): boolean {
  return key in catalogs[current] || key in catalogs.fr;
}

export function t(key: string, vars?: Vars): string {
  let k = key;
  if (vars && typeof vars.count === "number") {
    const form = new Intl.PluralRules(LOCALES[current]).select(vars.count) === "one" ? "one" : "other";
    if (`${key}_${form}` in catalogs[current] || `${key}_${form}` in catalogs.fr) k = `${key}_${form}`;
  }
  const raw = catalogs[current][k] ?? catalogs.fr[k] ?? key;
  if (!vars) return raw;
  return raw.replace(/\{(\w+)\}/g, (m, name: string) => {
    const v = vars[name];
    if (v === undefined) return m;
    return typeof v === "number" ? new Intl.NumberFormat(LOCALES[current]).format(v) : v;
  });
}
