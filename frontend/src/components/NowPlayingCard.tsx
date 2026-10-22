import { CheckCircle2, Save, Square } from "lucide-react";
import { useState } from "react";

import { imageUrl } from "../api/client";
import { useCaps, useNowPlaying, useQuitGame, useSaveStateNow } from "../api/queries";
import { useT } from "../i18n";
import { ConsoleBadge } from "./ConsoleBadge";
import { ScreenshotButton } from "./Screenshots";
import { Cover } from "./Cover";
import { VolumeControl } from "./VolumeControl";
import { errorMessage } from "./ui";

/** Tableau de bord : le jeu qui tourne sur la console, avec « Sauvegarder maintenant », « Quitter le jeu » et
 * « Capture d'écran ». */
export function NowPlayingCard({ online, onOpen }: { online: boolean; onOpen?: (id: number) => void }) {
  const t = useT();
  const now = useNowPlaying(online).data;
  const quit = useQuitGame();
  const save = useSaveStateNow();
  const caps = useCaps();
  if (!now?.playing) return null;
  const title = now.game?.title ?? now.rom_path?.split("/").pop() ?? now.process ?? "";
  const ra = now.process === "retroarch";
  return (
    <section className="block now-card" aria-labelledby="now-h">
      <Atmosphere key={now.game?.id ?? "none"} sources={now.game ? [imageUrl(now.game, "full"), now.game.boxart_url ? `${now.game.boxart_url}?size=full` : null] : []} />
      {now.game && (
        <div className="now-card__frame">
          {onOpen
            ? <button type="button" className="now-card__open" onClick={() => onOpen(now.game!.id)} aria-label={t("dashboard.openSheet", { title })}>
                <Cover game={now.game} className="now-card__cover" />
              </button>
            : <Cover game={now.game} className="now-card__cover" />}
        </div>
      )}
      <div className="now-card__body">
        <p className="now-card__label"><span className="led led--live" aria-hidden /> {t("dashboard.nowPlaying")}</p>
        <h2 id="now-h" className="now-card__title">
          {now.game && onOpen
            ? <button type="button" className="link-button now-card__title-link" onClick={() => onOpen(now.game!.id)}>{title}</button>
            : title}
        </h2>
        {now.game && <p className="muted now-card__platform"><ConsoleBadge code={now.game.platform.code} label={now.game.platform.label} />
          {now.game.platform.label}</p>}
        <VolumeControl online={online} />
        <div className="now-card__actions">
          {ra && caps.save_state && (
            <button type="button" className="button button--small button--save" onClick={() => save.mutate()} disabled={save.isPending}>
              <Save size={16} aria-hidden /> {save.isPending ? t("dashboard.saving") : t("dashboard.saveNow")}
            </button>
          )}
          {(ra || !caps.resume_slot) && caps.quit && (
            <button type="button" className="button button--small button--danger" onClick={() => quit.mutate()} disabled={quit.isPending}>
              <Square size={16} fill="currentColor" aria-hidden /> {quit.isPending ? t("common.device.quitting") : t("common.device.quit")}
            </button>
          )}
          {save.isSuccess && <span className="ok-text" role="status"><CheckCircle2 size={16} aria-hidden /> {t("dashboard.saved")}</span>}
          {now.game && <ScreenshotButton variant="small" label="full" />}
        </div>
        {!((ra || !caps.resume_slot) && caps.quit) && <p className="muted">{t("dashboard.quitOnConsole")}</p>}
        {(save.isError || quit.isError) && <p className="text-error">{errorMessage(save.error ?? quit.error)}</p>}
      </div>
    </section>
  );
}

/**
 * Fond d'ambiance de la carte : la première image du jeu disponible (capture du dossier Imgs, sinon jaquette),
 * agrandie et floutée sous un dégradé sombre. Sans image, un simple dégradé néon.
 */
function Atmosphere({ sources }: { sources: (string | null)[] }) {
  const list = sources.filter((s): s is string => !!s);
  const [index, setIndex] = useState(0);
  const src = list[index];
  return (
    <div className={`now-card__art ${src ? "" : "now-card__art--abstract"}`} aria-hidden>
      {src && <img key={src} src={src} alt="" decoding="async" onError={() => setIndex((i) => i + 1)} />}
    </div>
  );
}
