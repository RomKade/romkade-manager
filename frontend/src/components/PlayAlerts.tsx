import { Hourglass, X } from "lucide-react";
import { Link } from "react-router-dom";

import { useAckAlert, usePlayState } from "../api/queries";
import { useT } from "../i18n";
import { useDuration } from "../pages/Playtime";

/** Pop-in « ça fait 4 h que tu joues » : affichée sur toutes les pages tant qu'elle n'est pas fermée. */
export function PlayAlerts() {
  const t = useT();
  const dur = useDuration();
  const alerts = usePlayState().data?.alerts ?? [];
  const ack = useAckAlert();
  const a = alerts[alerts.length - 1];
  if (!a) return null;
  const paused = alerts.some((x) => x.console_pause);  // jeu figé sur la console : « OK » le relance
  return (
    <div className="play-alert" role="alertdialog" aria-labelledby="play-alert-t" aria-describedby="play-alert-d">
      <Hourglass size={22} aria-hidden className="play-alert__icon" />
      <div className="play-alert__body">
        <p id="play-alert-t" className="play-alert__title">
          {t(a.scope === "day" ? "playtime.alert.titleDay" : "playtime.alert.titleSession", { d: dur(a.minutes * 60) })}
        </p>
        <p id="play-alert-d">{t("playtime.alert.body", { game: a.game_title })}</p>
        {paused && <p className="muted">{t("playtime.alert.paused")}</p>}
        <div className="play-alert__actions">
          <button type="button" className="button button--primary button--small"
            onClick={() => alerts.forEach((x) => ack.mutate(x.id))}>{t(paused ? "playtime.alert.resume" : "playtime.alert.ok")}</button>
          <Link to="/parametres/temps-de-jeu" className="link">{t("playtime.alert.settings")}</Link>
        </div>
      </div>
      <button type="button" className="icon-button play-alert__close" aria-label={t("playtime.alert.close")}
        onClick={() => alerts.forEach((x) => ack.mutate(x.id))}>
        <X size={16} aria-hidden />
      </button>
    </div>
  );
}
