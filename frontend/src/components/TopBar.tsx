import * as Popover from "@radix-ui/react-popover";
import { Check, ChevronDown, Square } from "lucide-react";
import { useState } from "react";
import { useLocation } from "react-router-dom";

import { useDeviceStatus, useNowPlaying, useQuitGame } from "../api/queries";
import { LANGS, setLang, useLang, useT } from "../i18n";
import { ConsoleBadge } from "./ConsoleBadge";
import { Cover } from "./Cover";
import { Flag } from "./Flag";
import { GameSheet } from "./GameSheet";
import { QuickSearch } from "./QuickSearch";
import { ScreenshotButton } from "./Screenshots";
import { errorMessage } from "./ui";
import { VolumeControl } from "./VolumeControl";

/** Barre du haut, sur toutes les pages : recherche, jeu en cours sur la console, choix de la langue. */
export function TopBar() {
  // Fiche ouverte depuis la recherche ou le jeu en cours, par-dessus la page affichée.
  const [openId, setOpenId] = useState<number | null>(null);
  return (
    <div className="topbar">
      <QuickSearch onOpen={setOpenId} />
      <NowPlayingChip onOpen={setOpenId} />
      <LanguageSwitcher />
      <GameSheet id={openId} onClose={() => setOpenId(null)} onOpen={setOpenId} />
    </div>
  );
}

/** Langue : bouton compact (drapeau + code) et petit menu déroulant. Sur téléphone, fixé en haut à droite. */
export function LanguageSwitcher() {
  const t = useT();
  const lang = useLang();
  const [open, setOpen] = useState(false);
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger className="lang-switch" aria-label={t("common.lang.label")} title={t("common.lang.label")}>
        <Flag lang={lang} />
        <span className="lang-switch__code">{lang.toUpperCase()}</span>
        <ChevronDown size={14} aria-hidden />
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className="popover lang-menu" align="end" sideOffset={6}>
          <ul role="list" aria-label={t("common.lang.label")}>
            {LANGS.map((l) => (
              <li key={l.code}>
                <button type="button" className={`lang-menu__item ${lang === l.code ? "is-on" : ""}`} lang={l.code}
                  aria-pressed={lang === l.code} onClick={() => { setLang(l.code); setOpen(false); }}>
                  <Flag lang={l.code} /> {l.label}
                  {lang === l.code && <Check size={14} aria-hidden className="lang-menu__check" />}
                </button>
              </li>
            ))}
          </ul>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function NowPlayingChip({ onOpen }: { onOpen: (id: number) => void }) {
  const t = useT();
  // Le tableau de bord affiche déjà le jeu en cours en grand.
  const onDashboard = useLocation().pathname === "/";
  const online = useDeviceStatus().data?.connected === true;
  const now = useNowPlaying(online).data;
  const quit = useQuitGame();
  if (!now?.playing || onDashboard) return null;
  const title = now.game?.title ?? now.rom_path?.split("/").pop() ?? now.process ?? "";
  return (
    <section className="now-chip" role="status" aria-label={t("common.device.live")}>
      {now.game && (
        <button type="button" className="now-chip__cover" onClick={() => onOpen(now.game!.id)} tabIndex={-1} aria-hidden>
          <Cover game={now.game} />
        </button>
      )}
      <div className="now-chip__info">
        <span className="now-chip__label"><span className="led led--live" aria-hidden /> {t("common.device.live")}</span>
        {now.game
          ? <button type="button" className="now-chip__title" onClick={() => onOpen(now.game!.id)} title={title}>{title}</button>
          : <span className="now-chip__title" title={title}>{title}</span>}
        {now.game && <span className="now-chip__platform"><ConsoleBadge code={now.game.platform.code} label={now.game.platform.label} /></span>}
      </div>
      <div className="now-chip__controls">
        <VolumeControl online={online} compact />
        {now.game && <ScreenshotButton variant="chip" />}
        {now.process === "retroarch" && (
          <button type="button" className="now-chip__stop" onClick={() => quit.mutate()} disabled={quit.isPending}>
            <Square size={12} fill="currentColor" aria-hidden /> {quit.isPending ? t("common.device.quitting") : t("common.device.quit")}
          </button>
        )}
      </div>
      {quit.isError && <p className="text-error now-chip__error">{errorMessage(quit.error)}</p>}
    </section>
  );
}
