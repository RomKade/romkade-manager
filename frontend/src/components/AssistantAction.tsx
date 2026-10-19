import { useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Play, Save, Square, Volume2, VolumeX, X } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";
import { useT } from "../i18n";
import type { ActionState, ConsoleAction } from "../lib/assistant";
import { errorMessage } from "./ui";

const STEP = 20; // « plus fort », « moins fort » : de 20 points

/**
 * Action sur la console proposée par l'assistant (« lance Tetris », « mets le son à 50 % ») : rien ne part vers la
 * console avant le clic sur le bouton. Le résultat (fait, annulé, échec) reste affiché dans la conversation.
 */
export function AssistantAction({ action, state, note, onSettle }: {
  action: ConsoleAction; state?: ActionState; note?: string; onSettle: (state: ActionState, note?: string) => void;
}) {
  const t = useT();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const k = action.kind;

  const run = async (gameId?: number) => {
    setBusy(true);
    try {
      if (k === "launch_game" && gameId != null) await api.launchGame(gameId, null);
      else if (k === "quit_game") await api.quitGame();
      else if (k === "save_state") await api.saveStateNow();
      else if (k === "set_volume") await api.setVolume({ percent: action.percent ?? 50 });
      else if (k === "mute" || k === "unmute") await api.setVolume({ muted: k === "mute" });
      else if (k === "volume_up" || k === "volume_down") {
        const v = await api.volume();
        await api.setVolume({ percent: Math.max(0, Math.min(100, v.percent + (k === "volume_up" ? STEP : -STEP))), muted: false });
      }
      for (const key of ["now-playing", "volume", "recent-played"]) qc.invalidateQueries({ queryKey: [key] });
      onSettle("done");
    } catch (err) {
      onSettle("failed", errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (!action.supported) return <p className="assistant__action assistant__action--off">{t("assistant.action.unsupported", { system: action.system })}</p>;
  if (k === "launch_game" && action.games.length === 0) return <p className="assistant__action assistant__action--off">{t("assistant.action.notFound")}</p>;

  const first = action.games[0];
  const question = k === "launch_game" && first ? t("assistant.action.ask.launch_game", { title: first.title, platform: first.platform })
    : t(`assistant.action.ask.${k}`, { percent: action.percent ?? 0 });
  const Icon = k === "launch_game" ? Play : k === "quit_game" ? Square : k === "save_state" ? Save : k === "mute" ? VolumeX : Volume2;

  return (
    <div className="assistant__action" role="group" aria-label={question}>
      <p className="assistant__action-q"><Icon size={14} aria-hidden /> {question}</p>
      {state ? (
        <p className={`assistant__action-result is-${state}`} role="status">
          {state === "done" && <Check size={13} aria-hidden />} {state === "failed" ? note : t(`assistant.action.${state}`)}
        </p>
      ) : (
        <div className="assistant__action-buttons">
          {k === "launch_game" ? action.games.map((g, i) => (
            <button key={g.id} type="button" className={`button button--small ${i === 0 ? "button--primary" : ""}`} disabled={busy} onClick={() => run(g.id)}>
              {busy ? <Loader2 size={13} aria-hidden className="spin" /> : <Play size={13} aria-hidden />}
              {i === 0 ? t("assistant.action.confirm.launch_game") : `${g.title} · ${g.platform}`}
            </button>
          )) : (
            <button type="button" className="button button--primary button--small" disabled={busy} onClick={() => run()}>
              {busy ? <Loader2 size={13} aria-hidden className="spin" /> : <Icon size={13} aria-hidden />} {t(`assistant.action.confirm.${k}`)}
            </button>
          )}
          <button type="button" className="button button--small" disabled={busy} onClick={() => onSettle("cancelled")}>
            <X size={13} aria-hidden /> {t("assistant.action.cancel")}
          </button>
        </div>
      )}
    </div>
  );
}
