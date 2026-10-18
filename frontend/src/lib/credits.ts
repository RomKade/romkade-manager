import { useQuery } from "@tanstack/react-query";

import { getLang } from "../i18n";

/** Dépôt du projet : lien « GitHub » de la barre latérale et de Paramètres > Sources et crédits. */
export const REPO = { owner: "RomKade", name: "romkade-manager" } as const;
export const REPO_URL = `https://github.com/${REPO.owner}/${REPO.name}`;
/** Documentation en ligne (romkade.com/docs, MkDocs) dans la langue de l'interface : anglais à la racine, /fr/, /es/. */
export const DOCS_URL = "https://romkade.com/docs/";
export const docsUrl = () => `${DOCS_URL}${getLang() === "en" ? "" : `${getLang()}/`}`;

/**
 * Nombre d'étoiles du dépôt, lu sur l'API publique de GitHub (sans clé, une fois toutes les 6 h au plus).
 * null tant que le dépôt est privé ou si GitHub ne répond pas : le lien s'affiche alors sans compteur.
 */
export function useGitHubStars() {
  return useQuery({
    queryKey: ["github-stars", REPO_URL],
    queryFn: async (): Promise<number | null> => {
      const res = await fetch(`https://api.github.com/repos/${REPO.owner}/${REPO.name}`, { headers: { Accept: "application/vnd.github+json" } });
      if (!res.ok) return null;
      const n = (await res.json())?.stargazers_count;
      return typeof n === "number" ? n : null;
    },
    staleTime: 6 * 3600_000,
    gcTime: Infinity,
    retry: false,
    refetchOnWindowFocus: false,
  });
}

/** « 1234 » -> « 1,2 k ». */
export function starCount(n: number, locale: string): string {
  return n < 1000 ? String(n) : `${(n / 1000).toLocaleString(locale, { maximumFractionDigits: 1 })} k`;
}

export type Credit = {
  id: string;
  name: string;
  url: string;
  /** Licence du contenu repris, seulement quand elle est connue avec certitude. */
  license?: string;
};

/**
 * Contenus repris d'ailleurs, affichés dans Paramètres > Sources et crédits (usage : settings.credits.<id>).
 * Ajouter une ligne ici à chaque nouvelle source (script de construction, service en ligne, illustration).
 */
export const CREDITS: { group: "data" | "media" | "online" | "ui"; items: Credit[] }[] = [
  { group: "media", items: [
    { id: "thumbnails", name: "libretro-thumbnails", url: "https://github.com/libretro-thumbnails/libretro-thumbnails" },
    { id: "assets", name: "libretro / retroarch-assets", url: "https://github.com/libretro/retroarch-assets", license: "CC BY 4.0" },
  ] },
  { group: "data", items: [
    { id: "database", name: "libretro-database", url: "https://github.com/libretro/libretro-database" },
    { id: "openvgdb", name: "OpenVGDB", url: "https://github.com/OpenVGDB/OpenVGDB", license: "MIT" },
    { id: "catver", name: "catver.ini (progettoSNAPS)", url: "https://www.progettosnaps.net/catver/" },
    { id: "arcade", name: "MAME, FBNeo, HBMAME", url: "https://www.mamedev.org/" },
  ] },
  { group: "online", items: [
    { id: "wikipedia", name: "Wikipédia", url: "https://www.wikipedia.org/" },
    { id: "gamefaqs", name: "GameFAQs", url: "https://gamefaqs.gamespot.com/" },
    { id: "youtube", name: "YouTube", url: "https://www.youtube.com/" },
    { id: "claude", name: "Claude (Anthropic)", url: "https://www.anthropic.com/claude" },
  ] },
  { group: "ui", items: [
    { id: "lucide", name: "Lucide", url: "https://lucide.dev/", license: "ISC" },
    { id: "fonts", name: "Archivo, Atkinson Hyperlegible Next", url: "https://fontsource.org/", license: "SIL OFL 1.1" },
  ] },
];

export const creditUrl = (id: string) => CREDITS.flatMap((g) => g.items).find((c) => c.id === id)!.url;
