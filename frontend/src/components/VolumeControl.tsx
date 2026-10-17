import { Volume1, Volume2, VolumeX } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";

import { useCaps, useSetVolume, useVolume } from "../api/queries";
import { useT } from "../i18n";
import { errorMessage } from "./ui";

/** Volume des jeux (réglage « Game Manager » de la console, toutes sorties) : couper / remettre le son et curseur.
 * `compact` : version de la barre du haut. */
export function VolumeControl({ online, compact = false }: { online: boolean; compact?: boolean }) {
  const t = useT();
  const enabled = useCaps().volume && online;
  const q = useVolume(enabled);
  const set = useSetVolume();
  const v = q.data;
  // Valeur affichée pendant qu'on glisse le curseur ; envoyée à la console après une courte pause.
  const [draft, setDraft] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  if (!enabled || !v || v.mode === "none") return null;
  const percent = draft ?? (v.muted ? 0 : v.percent);
  const muted = draft == null ? v.muted : draft === 0;
  const Icon = muted ? VolumeX : percent < 50 ? Volume1 : Volume2;
  const slide = (value: number) => {
    setDraft(value);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => set.mutate({ percent: value }, { onSettled: () => setDraft(null) }), 250);
  };

  return (
    <div className={`volume ${compact ? "volume--compact" : ""}`}>
      <button type="button" className="icon-button volume__mute" onClick={() => set.mutate({ muted: !v.muted })}
        disabled={set.isPending} aria-pressed={v.muted}
        title={v.muted ? t("common.volume.unmute") : t("common.volume.mute")}
        aria-label={v.muted ? t("common.volume.unmute") : t("common.volume.mute")}>
        <Icon size={compact ? 15 : 18} aria-hidden />
      </button>
      {v.adjustable ? (
        <>
          <input type="range" className="volume__slider" min={0} max={100} step={5} value={percent}
            style={{ "--pct": `${percent}%` } as CSSProperties}
            aria-label={t("common.volume.label")} onChange={(e) => slide(Number(e.target.value))} />
          <span className="volume__value" aria-hidden>{muted ? t("common.volume.muted") : `${percent} %`}</span>
        </>
      ) : compact ? null : (
        // Jeu lancé depuis le menu de la console : seule la coupure marche.
        <span className="volume__note">{t("common.volume.notReady")}</span>
      )}
      {!compact && set.isError && <span className="text-error">{errorMessage(set.error)}</span>}
    </div>
  );
}
