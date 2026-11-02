import { useQueryClient } from "@tanstack/react-query";
import { ThumbsDown, ThumbsUp, X } from "lucide-react";

import type { Game } from "../api/client";
import { usePlayState, useSetDislike, useSetLike, useSkipOpinion } from "../api/queries";
import { useT } from "../i18n";
import { Cover } from "./Cover";

/** Pop-in « Tu as aimé ? » après une partie terminée (5 min au moins), tant qu'aucun avis n'a été donné sur ce
 * jeu : « J'aime », « Je n'aime pas » ou « Sans avis », qui ne la repose plus. Elle attend que les alertes de
 * temps de jeu soient fermées. */
export function OpinionPrompt() {
  const state = usePlayState().data;
  const game = state?.opinion;
  if (!game || state.alerts.length) return null;
  return <Prompt key={game.id} game={game} />;
}

function Prompt({ game }: { game: Game }) {
  const t = useT();
  const qc = useQueryClient();
  const like = useSetLike(game.id);
  const dislike = useSetDislike(game.id);
  const skip = useSkipOpinion();
  const busy = like.isPending || dislike.isPending || skip.isPending;
  const answered = { onSuccess: () => qc.invalidateQueries({ queryKey: ["play-state"] }) };
  return (
    <div className="play-alert play-alert--opinion" role="dialog" aria-labelledby="opinion-t" aria-describedby="opinion-d">
      <Cover game={game} className="play-alert__cover" />
      <div className="play-alert__body">
        <p id="opinion-t" className="play-alert__title">{t("playtime.opinion.title", { game: game.title })}</p>
        <p id="opinion-d" className="muted">{t("playtime.opinion.body")}</p>
        <div className="play-alert__actions play-alert__actions--opinion">
          <button type="button" className="button button--primary button--small" disabled={busy}
            onClick={() => like.mutate(true, answered)}>
            <ThumbsUp size={16} aria-hidden /> {t("playtime.opinion.like")}
          </button>
          <button type="button" className="button button--small" disabled={busy}
            onClick={() => dislike.mutate(true, answered)}>
            <ThumbsDown size={16} aria-hidden /> {t("playtime.opinion.dislike")}
          </button>
          <button type="button" className="link-button" disabled={busy} onClick={() => skip.mutate(game.id)}>
            {t("playtime.opinion.skip")}
          </button>
        </div>
      </div>
      <button type="button" className="icon-button play-alert__close" aria-label={t("playtime.opinion.close")}
        disabled={busy} onClick={() => skip.mutate(game.id)}>
        <X size={16} aria-hidden />
      </button>
    </div>
  );
}
