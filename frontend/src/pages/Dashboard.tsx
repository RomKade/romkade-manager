import { ArrowRight, Box, CheckCircle2, Gamepad2, HardDriveUpload, Play, RefreshCw } from "lucide-react";
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";

import {
  isActive, useCaps, useDeviceStatus, useLaunchGame, useNowPlaying, usePlatforms, usePlayState, useRecentGames, useRecentPlayed, useStartSync,
  useStatus, useTransfers,
} from "../api/queries";
import { ConsoleBadge } from "../components/ConsoleBadge";
import { Cover } from "../components/Cover";
import { GameSheet } from "../components/GameSheet";
import { NowPlayingCard } from "../components/NowPlayingCard";
import { Shelf } from "../components/Shelf";
import { StorageBar } from "../components/StorageBar";
import { Empty, ErrorNotice, errorMessage, Spinner } from "../components/ui";
import { locale, useT } from "../i18n";
import { ago, count, gb } from "../lib/format";
import { LimitGauge, useDuration } from "./Playtime";

/**
 * « 4 838 jeux sur 34 consoles » : la phrase reste celle de la traduction (et son nom accessible inchangé),
 * seuls les deux nombres sont mis en couleur (jeux en cyan, consoles en rose).
 */
function HeroTitle({ games, consoles }: { games: number; consoles: number }) {
  const t = useT();
  const nf = new Intl.NumberFormat(locale());
  const highlight = (text: string, n: number, kind: "games" | "consoles") => {
    const num = nf.format(n);
    const at = text.indexOf(num);
    if (at < 0) return text;
    return <>{text.slice(0, at)}<span className={`hero__num hero__num--${kind}`}>{num}</span>{text.slice(at + num.length)}</>;
  };
  const parts = {
    games: highlight(t("dashboard.games", { count: games }), games, "games"),
    consoles: highlight(t("dashboard.consoles", { count: consoles }), consoles, "consoles"),
  };
  // Les marqueurs \u0001 / \u0002 repèrent l'emplacement de chaque morceau dans la phrase traduite.
  return (
    <>
      {t("dashboard.title", { games: "\u0001", consoles: "\u0002" }).split(/([\u0001\u0002])/).map((chunk, i) => (
        <Fragment key={i}>{chunk === "\u0001" ? parts.games : chunk === "\u0002" ? parts.consoles : chunk}</Fragment>
      ))}
    </>
  );
}

export function DashboardPage() {
  const t = useT();
  const status = useStatus();
  const platforms = usePlatforms();
  const recent = useRecentGames();
  const device = useDeviceStatus();
  const start = useStartSync(() => undefined);
  const [openId, setOpenId] = useState<number | null>(null);
  const activeTransfers = (useTransfers().data ?? []).filter(isActive);
  const played = useRecentPlayed();
  const play = usePlayState();
  const dur = useDuration();
  // Même requête que la carte « jeu en cours » (cache partagé) : sert à entourer ce jeu dans « Joués récemment ».
  const nowPlaying = useNowPlaying(device.data?.connected === true);
  // Premier de la liste : l'historique de la console donne l'ordre, la date n'est connue que si Game Manager l'a suivi.
  const lastPlayed = played.data?.[0];
  const limit = play.data?.settings.alert_enabled ? play.data.settings.alert_minutes * 60 : null;

  if (status.isPending) return <div className="page"><Spinner label={t("common.loading")} /></div>;
  if (status.isError) return <div className="page"><ErrorNotice error={status.error} /></div>;
  const s = status.data;
  const run = s.last_run;
  const online = device.data?.connected;
  const nowId = nowPlaying.data?.playing ? nowPlaying.data.game?.id : undefined;

  return (
    <div className="page dashboard">
      <section className="hero" aria-labelledby="hero-h">
        <h1 id="hero-h" className="hero__line">
          {s.synced ? (
            <HeroTitle games={s.game_count} consoles={s.platform_count} />
          ) : (
            t("dashboard.notSynced")
          )}
        </h1>
        <p className="hero__sub">
          {s.synced ? (
            <>
              {t("dashboard.summary", { files: t("dashboard.files", { count: s.file_count }), size: gb(s.total_bytes) })}{" "}
              {s.storage_free_bytes != null && <>{t("dashboard.freeLeft", { free: gb(s.storage_free_bytes) })}{" "}</>}
              {t("dashboard.readAgo", { ago: ago(s.last_successful_sync_at) })}
            </>
          ) : (
            t("dashboard.notSyncedSub")
          )}
        </p>
        <div className="hero__actions">
          <button
            type="button"
            className="button button--neon"
            onClick={() => start.mutate()}
            disabled={s.sync_running || start.isPending || online === false}
          >
            <RefreshCw size={16} aria-hidden className={s.sync_running ? "spin" : ""} />
            {s.sync_running
              ? run
                ? t("dashboard.syncProgress", { done: run.platforms_done, total: run.platforms_total })
                : t("dashboard.syncing")
              : t("dashboard.sync")}
          </button>
          {online === false && <p className="muted">{t("dashboard.offline")}</p>}
          {run?.status === "failed" && !s.sync_running && (
            <p className="text-error">{t("dashboard.lastFailed")} <Link to="/synchronisation">{t("dashboard.seeDetail")}</Link></p>
          )}
        </div>
        {start.isError && <ErrorNotice error={start.error} />}
      </section>

      <NowPlayingCard online={online === true} onOpen={setOpenId} />

      <section className="block" aria-labelledby="played-h">
        <div className="block__head">
          <h2 id="played-h"><Gamepad2 size={22} aria-hidden />{t("dashboard.played")}</h2>
          <Link to="/temps-de-jeu" className="link link--arrow">{t("dashboard.playedAll")} <ArrowRight size={15} aria-hidden /></Link>
        </div>
        {played.isPending ? <Spinner label={t("common.loading")} /> : played.isError ? <ErrorNotice error={played.error} /> : (played.data ?? []).length === 0 ? (
          <p className="muted">{t("dashboard.playedEmpty")}</p>
        ) : (
          <Shelf label={t("dashboard.played")}>
            {played.data!.map((p) => (
              <div key={p.rom_path} className={`shelf__item shelf__item--played ${p.game && p.game.id === nowId ? "is-current" : ""}`}>
                <button type="button" className="shelf__open" onClick={() => p.game && setOpenId(p.game.id)} disabled={!p.game}>
                  {p.game ? <Cover game={p.game} /> : <span className="cover cover--empty" aria-hidden><span className="cover__platform">{p.platform}</span></span>}
                  <span className="tile__title">{p.title}</span>
                  <span className="tile__meta">
                    {(p.game?.platform.code ?? p.platform) && <ConsoleBadge code={p.game?.platform.code ?? p.platform!} label={p.game?.platform.label} />}
                    {[p.last_played ? ago(p.last_played) : null, p.seconds ? dur(p.seconds) : null].filter(Boolean).join(" · ")}
                  </span>
                </button>
                {p.game?.present && <ReplayButton id={p.game.id} title={p.title} />}
              </div>
            ))}
          </Shelf>
        )}
      </section>

      <section className="block" aria-labelledby="recent-h">
        <div className="block__head">
          <h2 id="recent-h"><Box size={22} aria-hidden />{t("dashboard.recent")}</h2>
          <span className="block__links">
            <Link to="/ajouter-des-jeux" className="button button--small"><HardDriveUpload size={14} aria-hidden /> {t("dashboard.addGames")}</Link>
            <Link to="/bibliotheque?sort=added" className="link link--arrow">{t("dashboard.seeAll")} <ArrowRight size={15} aria-hidden /></Link>
          </span>
        </div>
        {recent.isPending ? <Spinner label={t("common.loading")} /> : recent.isError ? <ErrorNotice error={recent.error} /> : recent.data && recent.data.items.length > 0 ? (
          <Shelf label={t("dashboard.recent")}>
            {recent.data.items.map((g) => (
              <button key={g.id} type="button" className="shelf__item" onClick={() => setOpenId(g.id)}>
                <Cover game={g} />
                <span className="tile__title">{g.title}</span>
                <span className="tile__meta"><ConsoleBadge code={g.platform.code} label={g.platform.label} />{ago(g.first_seen_at)}</span>
              </button>
            ))}
          </Shelf>
        ) : (
          <Empty title={t("dashboard.emptyTitle")}>
            <p>{t("dashboard.emptyBody")}</p>
          </Empty>
        )}
      </section>

      {s.storage_total_bytes != null && s.storage_free_bytes != null && platforms.data && (
        <section className="block" aria-labelledby="sd-h">
          <h2 id="sd-h">{t("dashboard.sd")}</h2>
          <StorageBar platforms={platforms.data} total={s.storage_total_bytes} free={s.storage_free_bytes} />
        </section>
      )}

      <div className="dashboard__cols">
        <section className="block" aria-labelledby="plat-h">
          <div className="block__head">
            <h2 id="plat-h">{t("dashboard.topConsoles")}</h2>
            <Link to="/bibliotheque" className="link">{t("dashboard.allConsoles")}</Link>
          </div>
          <ol className="rank">
            {(platforms.data ?? [])
              .filter((p) => p.game_count > 0)
              .sort((a, b) => b.game_count - a.game_count)
              .slice(0, 8)
              .map((p) => {
                const max = Math.max(...(platforms.data ?? []).map((x) => x.game_count), 1);
                return (
                  <li key={p.id}>
                    <Link to={`/bibliotheque?platform=${p.directory}`} className="rank__label">{p.label ?? p.directory}</Link>
                    <span className="rank__bar" aria-hidden><span style={{ width: `${(p.game_count / max) * 100}%` }} /></span>
                    <span className="rank__value num">{count(p.game_count)}</span>
                  </li>
                );
              })}
          </ol>
        </section>

        <section className="block" aria-labelledby="sync-h">
          <h2 id="sync-h">{t("dashboard.activity")}</h2>
          <dl className="facts facts--compact">
            <div>
              <dt>{t("dashboard.lastPlayed")}</dt>
              <dd>
                {!lastPlayed ? t("dashboard.none") : lastPlayed.last_played
                  ? t("dashboard.lastPlayedValue", { title: lastPlayed.title, ago: ago(lastPlayed.last_played) })
                  : lastPlayed.title}
              </dd>
            </div>
            <div>
              <dt>{t("dashboard.playToday")}</dt>
              <dd>
                <Link to="/temps-de-jeu">{dur(play.data?.today_seconds ?? 0)}</Link>
                {limit != null && play.data?.settings.alert_scope === "day" && (
                  <LimitGauge value={play.data.today_seconds} limit={limit} />
                )}
              </dd>
            </div>
            <div><dt>{t("dashboard.lastSync")}</dt><dd>{run ? ago(run.finished_at ?? run.started_at) : t("common.value.never")}</dd></div>
            {run && run.status !== "running" && (
              <div><dt>{t("dashboard.changes")}</dt><dd className="num">{t("dashboard.changesValue", { added: run.added, modified: run.modified, removed: run.removed })}</dd></div>
            )}
            <div>
              <dt>{t("dashboard.activeTransfers")}</dt>
              <dd>
                {activeTransfers.length === 0 ? t("dashboard.none") : (
                  <Link to="/ajouter-des-jeux">{t("dashboard.copying", { count: activeTransfers.length })}</Link>
                )}
              </dd>
            </div>
          </dl>
        </section>
      </div>
      <GameSheet id={openId} onClose={() => setOpenId(null)} onOpen={setOpenId} />
    </div>
  );
}

/** Relance un jeu joué récemment sur la console. */
function ReplayButton({ id, title }: { id: number; title: string }) {
  const t = useT();
  const launch = useLaunchGame();
  if (!useCaps().launch) return null;
  return (
    <>
      <button type="button" className="tile__play shelf__play" disabled={launch.isPending || launch.isSuccess}
        onClick={() => launch.mutate(id)} aria-label={t("dashboard.replay", { title })} title={t("dashboard.replayHint")}>
        {launch.isSuccess ? <CheckCircle2 size={15} aria-hidden /> : <Play size={14} fill="currentColor" aria-hidden />}
      </button>
      {launch.isError && <span className="text-error shelf__error" role="alert">{errorMessage(launch.error)}</span>}
    </>
  );
}
