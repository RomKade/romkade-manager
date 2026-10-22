import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useCaps, useScreenshots } from "../api/queries";
import { ConsoleBadge } from "../components/ConsoleBadge";
import { GameSheet } from "../components/GameSheet";
import { ShotGrid } from "../components/Screenshots";
import { Empty, ErrorNotice, PageHeader, Spinner } from "../components/ui";
import { useT } from "../i18n";

/** Captures : les captures d'écran des jeux, gardées sur le Mac, par jeu. `?game=id` amène à ce jeu. */
export function ScreenshotsPage() {
  const t = useT();
  const q = useScreenshots();
  const caps = useCaps();
  const [sp] = useSearchParams();
  const focus = Number(sp.get("game")) || null;
  const [openId, setOpenId] = useState<number | null>(null);
  const focusRef = useRef<HTMLElement>(null);
  const ready = !!q.data;
  useEffect(() => { if (ready) focusRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" }); }, [ready, focus]);

  return (
    <div className="page screenshots">
      <PageHeader title={t("screenshots.title")} lead={t(caps.screenshot ? "screenshots.lead" : "screenshots.leadUnsupported")} />
      {q.isPending ? <Spinner label={t("screenshots.loading")} /> : q.isError ? <ErrorNotice error={q.error} /> :
        q.data.length === 0 ? <Empty title={t("screenshots.none")}>{caps.screenshot && t("screenshots.noneHelp")}</Empty> : (
          q.data.map((g) => (
            <section key={g.game_id} className={`block shots-game ${g.game_id === focus ? "is-focus" : ""}`}
              aria-labelledby={`shots-${g.game_id}`} ref={g.game_id === focus ? focusRef : undefined}>
              <h2 id={`shots-${g.game_id}`} className="shots-game__title">
                {g.platform_code && <ConsoleBadge code={g.platform_code} label={g.platform_label ?? null} />}
                <button type="button" className="link-button" onClick={() => setOpenId(g.game_id)}>{g.title}</button>
                <span className="muted">{t("screenshots.count", { count: g.shots.length })}</span>
              </h2>
              <ShotGrid shots={g.shots} title={g.title} platform={g.platform_label} />
            </section>
          ))
        )}
      <GameSheet id={openId} onClose={() => setOpenId(null)} onOpen={setOpenId} />
    </div>
  );
}
