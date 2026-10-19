import { Camera, CheckCircle2, Download, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import type { Shot } from "../api/client";
import { useCaps, useDeleteScreenshot, useGameScreenshots, useTakeScreenshot } from "../api/queries";
import { useT } from "../i18n";
import { dateTime } from "../lib/format";
import { errorMessage } from "./ui";

/**
 * « Capture d'écran » du jeu en cours, rangée avec ses captures : carte du tableau de bord, bandeau de la fiche
 * (`small`) et bloc « jeu en cours » de la barre du haut (`chip`, à la taille de son bouton « Quitter »).
 */
export function ScreenshotButton({ variant }: { variant?: "small" | "chip" }) {
  const t = useT();
  const caps = useCaps();
  const take = useTakeScreenshot();
  if (!caps.screenshot) return null;
  const size = variant === "chip" ? 12 : variant === "small" ? 14 : 16;
  const className = variant === "chip" ? "now-chip__btn" : `button ${variant === "small" ? "button--small" : ""}`;
  return (
    <>
      {/* Bandeau étroit de la fiche : libellés courts, le libellé complet reste le nom du bouton et l'infobulle */}
      <button type="button" className={className} onClick={() => take.mutate()} disabled={take.isPending}
        {...(variant === "small" ? { "aria-label": t("screenshots.take"), title: t("screenshots.take") } : {})}>
        <Camera size={size} aria-hidden />{" "}
        {take.isPending ? t("screenshots.taking") : variant === "small" ? t("screenshots.takeShort") : t("screenshots.take")}
      </button>
      {take.isSuccess && (
        <span role="status">
          <Link className="ok-text" to={`/captures?game=${take.data.game_id}`}
            {...(variant === "small" ? { "aria-label": t("screenshots.taken"), title: t("screenshots.taken") } : {})}>
            <CheckCircle2 size={size} aria-hidden />{variant !== "small" && ` ${t("screenshots.taken")}`}
          </Link>
        </span>
      )}
      {take.isError && <span className="text-error" role="alert">{errorMessage(take.error)}</span>}
    </>
  );
}

/** Vignettes des captures : ouvrir en grand, télécharger, supprimer. */
export function ShotGrid({ shots, title }: { shots: Shot[]; title: string }) {
  const t = useT();
  const del = useDeleteScreenshot();
  return (
    <ul className="shots">
      {shots.map((s) => (
        <li key={s.url} className="shot">
          <a href={s.url} target="_blank" rel="noreferrer" className="shot__open" aria-label={t("screenshots.open", { date: dateTime(s.taken_at) })}>
            <img src={s.url} alt={t("screenshots.alt", { title, date: dateTime(s.taken_at) })} loading="lazy" decoding="async" />
          </a>
          <div className="shot__bar">
            <span className="muted num">{dateTime(s.taken_at)}</span>
            <a className="icon-button" href={s.url} download={`${title} ${s.name}`} aria-label={t("screenshots.download")} title={t("screenshots.download")}>
              <Download size={14} aria-hidden />
            </a>
            <button type="button" className="icon-button" onClick={() => del.mutate(s.url)} disabled={del.isPending}
              aria-label={t("screenshots.delete")} title={t("screenshots.delete")}>
              <Trash2 size={14} aria-hidden />
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Fiche d'un jeu : ses captures d'écran, s'il en a. */
export function GameScreenshots({ id, title }: { id: number; title: string }) {
  const t = useT();
  const q = useGameScreenshots(id);
  if (!q.data?.length) return null;
  return (
    <section className="sheet__section" aria-labelledby="shots-h">
      <h2 id="shots-h">{t("screenshots.mine")}</h2>
      <ShotGrid shots={q.data} title={title} />
      <Link to={`/captures?game=${id}`} className="link">{t("screenshots.all")}</Link>
    </section>
  );
}
