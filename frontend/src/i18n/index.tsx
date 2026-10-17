import { useSyncExternalStore } from "react";

import { getLang, has, subscribe, t } from "./core";

export { getLang, LANGS, locale, setLang, t, type Lang } from "./core";

/** Langue courante ; le composant se redessine quand elle change. */
export function useLang() {
  return useSyncExternalStore(subscribe, getLang, getLang);
}

/** `const t = useT()` dans un composant : la traduction suit le changement de langue. */
export function useT() {
  useLang();
  return t;
}

/** Régions déduites du nom de fichier (« USA, Europe »), renvoyées en français par le serveur. */
export function regionLabel(region: string | null | undefined): string {
  if (!region) return "";
  return region.split(", ").map((r) => (has(`common.region.${r}`) ? t(`common.region.${r}`) : r)).join(", ");
}
