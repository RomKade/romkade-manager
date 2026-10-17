import { ExternalLink, Sparkles } from "lucide-react";
import { useState } from "react";

import type { GameDetail } from "../api/client";
import { getLang, locale, useT } from "../i18n";
import { genreIcon } from "../lib/genreIcons";
import { regionFlag } from "../lib/regions";

/**
 * « Informations sur le jeu » de la fiche : genre (pictogramme), régions (drapeaux), sortie, éditeur, développeur,
 * franchise, résumé et fiche de référence. Données embarquées (libretro-database, OpenVGDB, listes arcade),
 * rapprochées par nom de fichier : voir backend app/services/gameinfo.py.
 */
export function GameInfo({ game }: { game: GameDetail }) {
  const t = useT();
  const [more, setMore] = useState(false);
  const GenreIcon = genreIcon(game.genre);
  const regions = game.region ? game.region.split(", ") : [];
  // Description dans la langue de l'interface (Claude), sinon le résumé d'origine en anglais.
  const lang = getLang();
  const mine = game.descriptions?.[lang] as { text: string; origin: string } | undefined;
  const summary = mine ? { text: mine.text, origin: mine.origin, lang }
    : game.description ? { text: game.description, origin: "source", lang: "en" } : null;
  const known = game.release_year || game.publisher || game.developer || summary;
  const long = (summary?.text.length ?? 0) > 420;
  return (
    <section className="sheet__section game-info" aria-labelledby="info-h">
      <h2 id="info-h">{t("sheet.info.title")}</h2>
      <dl className="facts">
        <div>
          <dt>{t("sheet.genre")}</dt>
          <dd className="game-info__genre">
            <span className="game-info__picto" aria-hidden><GenreIcon size={18} /></span>
            <span>
              {game.genre ? t(`common.genre.${game.genre}`) : t("sheet.unclassified")}
              {game.subgenre && <span className="game-info__sub"> · {t(`common.subgenre.${game.subgenre}`)}</span>}
              {game.genre_detail && game.genre_detail !== game.genre_label && (
                <span className="facts__note">{t("sheet.genreDetail", { detail: game.genre_detail })}</span>
              )}
            </span>
          </dd>
        </div>
        <div>
          <dt>{t("sheet.region")}</dt>
          <dd className="game-info__regions">
            {regions.length === 0 ? t("sheet.noRegion") : regions.map((r) => (
              <span key={r} className="game-info__region"><span aria-hidden>{regionFlag(r)}</span> {t(`common.region.${r}`)}</span>
            ))}
          </dd>
        </div>
        <div><dt>{t("sheet.info.released")}</dt><dd>{releaseLabel(game) ?? t("sheet.info.unknown")}</dd></div>
        {game.franchise && <div><dt>{t("sheet.info.franchise")}</dt><dd><WikiLinks names={game.franchise} /></dd></div>}
        <div><dt>{t("sheet.info.publisher")}</dt><dd>{game.publisher ? <WikiLinks names={game.publisher} /> : t("sheet.info.unknown")}</dd></div>
        <div><dt>{t("sheet.info.developer")}</dt><dd>{game.developer ? <WikiLinks names={game.developer} /> : t("sheet.info.unknown")}</dd></div>
      </dl>
      {summary && (
        <div className="game-info__summary">
          <h3>
            {t("sheet.info.summary")}
            {summary.lang !== getLang() && <span className="muted"> · {t("sheet.info.inEnglish")}</span>}
            {summary.origin && summary.origin !== "source" && (
              <span className="game-info__ai" title={t(`sheet.info.origin.${summary.origin}.hint`)}>
                <Sparkles size={12} aria-hidden /> {t(`sheet.info.origin.${summary.origin}`)}
              </span>
            )}
          </h3>
          <p lang={summary.lang} className={long && !more ? "is-clamped" : ""}>{summary.text}</p>
          {long && <button type="button" className="link-button" onClick={() => setMore(!more)}>{more ? t("sheet.info.less") : t("sheet.info.more")}</button>}
        </div>
      )}
      {game.info_url && (
        <a href={game.info_url} target="_blank" rel="noreferrer noopener" className="link game-info__ref">
          <ExternalLink size={14} aria-hidden /> {t("sheet.info.reference", { site: siteName(game.info_url) })}
        </a>
      )}
      <p className="muted game-info__sources">{known ? t("sheet.info.sources") : t("sheet.info.none")}</p>
    </section>
  );
}

/** « 2005-01-10 » -> « 10 janvier 2005 », « 2005-06 » -> « juin 2005 », sinon l'année. */
function releaseLabel(game: GameDetail): string | null {
  const d = game.release_date;
  if (d && /^\d{4}-\d{2}-\d{2}$/.test(d)) return new Date(`${d}T12:00:00`).toLocaleDateString(locale(), { day: "numeric", month: "long", year: "numeric" });
  if (d && /^\d{4}-\d{2}$/.test(d)) return new Date(`${d}-15T12:00:00`).toLocaleDateString(locale(), { month: "long", year: "numeric" });
  return game.release_year ? String(game.release_year) : null;
}

/**
 * Éditeur, développeur ou franchise : un lien Wikipédia (langue de l'interface) par nom. La recherche « go » de
 * Wikipédia ouvre directement l'article quand il existe, sinon la liste des résultats.
 * « Raizing / Eighting » -> deux liens ; « Irem (Taito license) » -> recherche « Irem ».
 */
function WikiLinks({ names }: { names: string }) {
  const parts = names.split(/\s+\/\s+|\s*;\s*/).filter(Boolean);
  return (
    <span className="game-info__links">
      {parts.map((name, i) => {
        const query = name.replace(/\s*\(.*?\)\s*/g, " ").replace(/\?$/, "").trim() || name;
        const url = `https://${getLang()}.wikipedia.org/w/index.php?search=${encodeURIComponent(query)}&go=Go`;
        return (
          <span key={name}>
            {i > 0 && " / "}
            <a href={url} target="_blank" rel="noreferrer noopener" className="link" title={`Wikipédia : ${query}`}>{name}</a>
          </span>
        );
      })}
    </span>
  );
}

function siteName(url: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    return host === "gamefaqs.com" ? "GameFAQs" : host;
  } catch {
    return url;
  }
}
