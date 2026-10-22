import { useMutation } from "@tanstack/react-query";
import { ExternalLink, Loader2, ScanText, Share2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, type Shot } from "../api/client";
import { getLang, useT } from "../i18n";
import type { AssistantGame } from "../lib/assistant";
import { errorMessage } from "./ui";

/** Partage d'une capture : partage du système (fichier) s'il existe, sinon image copiée, sinon téléchargée. */
async function shareShot(shot: Shot, title: string): Promise<"shared" | "copied" | "downloaded"> {
  const blob = await (await fetch(shot.url)).blob();
  const file = new File([blob], `${title} ${shot.name}`.replace(/[\\/:*?"<>|]/g, "-"), { type: "image/png" });
  if (navigator.canShare?.({ files: [file] })) {
    await navigator.share({ files: [file], title });
    return "shared";
  }
  if (typeof ClipboardItem !== "undefined" && navigator.clipboard?.write) {
    try {
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      return "copied";
    } catch { /* presse-papiers refusé : téléchargement */ }
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = file.name;
  a.click();
  URL.revokeObjectURL(a.href);
  return "downloaded";
}

/** Une capture dans la conversation : ouvrir, partager, et la faire lire par le modèle (texte, rôle des touches). */
export function ShotCard({ gameId, title, shot, autoFocus }: { gameId: number; title: string; shot: Shot; autoFocus?: boolean }) {
  const t = useT();
  const [shared, setShared] = useState<string | null>(null);
  const analyze = useMutation({ mutationFn: () => api.analyzeScreenshot(gameId, shot.name, getLang()) });
  const share = useMutation({ mutationFn: () => shareShot(shot, title), onSuccess: (r) => setShared(r) });
  const date = new Date(shot.taken_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  return (
    <figure className="assistant__shot">
      <a href={shot.url} target="_blank" rel="noreferrer noopener" title={t("assistant.shots.open")}>
        <img src={shot.url} alt={t("assistant.shots.alt", { title, date })} loading="lazy" />
      </a>
      <figcaption className="muted small">{date}</figcaption>
      <div className="assistant__shot-actions">
        <button type="button" className="button button--small button--primary" autoFocus={autoFocus}
          disabled={analyze.isPending} onClick={() => analyze.mutate()}>
          {analyze.isPending ? <Loader2 size={13} aria-hidden className="spin" /> : <ScanText size={13} aria-hidden />}{" "}
          {analyze.isPending ? t("assistant.shots.analyzing") : t("assistant.shots.analyze")}
        </button>
        <button type="button" className="button button--small" disabled={share.isPending} onClick={() => share.mutate()}>
          <Share2 size={13} aria-hidden /> {t("assistant.shots.share")}
        </button>
      </div>
      {shared && <p className="small muted" role="status">{t(`assistant.shots.${shared}`)}</p>}
      {share.isError && <p className="small text-error">{errorMessage(share.error)}</p>}
      {analyze.data && <p className="assistant__shot-text">{analyze.data.text}</p>}
      {analyze.isError && <p className="small text-error">{errorMessage(analyze.error)}</p>}
    </figure>
  );
}

/** « Montre mes captures », « analyse ma capture » : captures du jeu de la conversation, ou message s'il n'y en a pas. */
export function AssistantShots({ kind, game, shots }: { kind: string; game?: AssistantGame; shots: Shot[] }) {
  const t = useT();
  if (!game) return <p className="assistant__action assistant__action--off">{t("assistant.shots.noneAtAll")}</p>;
  if (shots.length === 0) {
    return (
      <div className="assistant__action">
        <p className="assistant__action-q">{t("assistant.shots.none", { title: game.title })}</p>
        <p className="small muted">{t("assistant.shots.noneHint")}</p>
      </div>
    );
  }
  const list = kind === "analyze_screenshot" ? shots.slice(0, 1) : shots;
  return (
    <div className="assistant__action">
      <p className="assistant__action-q">
        {t(kind === "analyze_screenshot" ? "assistant.shots.latest" : "assistant.shots.title", { title: game.title, count: shots.length })}
      </p>
      <div className="assistant__shots">
        {list.map((s, i) => <ShotCard key={s.name} gameId={game.id} title={game.title} shot={s} autoFocus={kind === "analyze_screenshot" && i === 0} />)}
      </div>
      <Link className="small" to={`/captures?game=${game.id}`}>{t("assistant.shots.all")} <ExternalLink size={11} aria-hidden /></Link>
    </div>
  );
}
