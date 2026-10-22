import { CalendarRange, Clock, Hourglass, Settings as SettingsIcon, Trash2, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import type { PlayStats } from "../api/client";
import { usePlayState, usePlayStats, useResetPlaytime, useStatus } from "../api/queries";
import { ConsoleBadge } from "../components/ConsoleBadge";
import { Cover } from "../components/Cover";
import { Empty, ErrorNotice, PageHeader, Spinner } from "../components/ui";
import { locale, useT } from "../i18n";
import { dateTime } from "../lib/format";

/** « 12 oct. 2026 » pour une date « AAAA-MM-JJ » (jour local). */
const fmtDate = (d: string) => new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", year: "numeric" }).format(new Date(`${d}T12:00:00`));

/** « 2 h 05 », « 45 min », « < 1 min ». */
export function useDuration() {
  const t = useT();
  return (seconds: number) => {
    const m = Math.floor(seconds / 60);
    if (seconds <= 0) return t("playtime.dur.m", { m: "0" });
    if (m < 1) return t("playtime.dur.lt1");
    const h = Math.floor(m / 60);
    return h ? t("playtime.dur.hm", { h: String(h), m: String(m % 60).padStart(2, "0") }) : t("playtime.dur.m", { m: String(m) });
  };
}

export function PlaytimePage() {
  const t = useT();
  const dur = useDuration();
  // Période « du … au … » : appliquée quand les deux dates sont choisies, dans le bon ordre.
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const period = from && to && from <= to ? { start: from, end: to } : null;
  const stats = usePlayStats(14, period);
  const base = usePlayStats(14);  // sans période : totaux RetroArch de chaque jeu, pour la remise à zéro
  const reset = useResetPlaytime();
  const [confirmAll, setConfirmAll] = useState(false);
  const raByKey = new Map((base.data?.games ?? []).map((g) => [g.key, g.ra_seconds]));
  const resetGame = (key: string) => reset.mutate({ games: [{ key, ra_seconds: raByKey.get(key) ?? 0 }] });
  const resetAll = () => reset.mutate({ games: (base.data?.games ?? []).map((g) => ({ key: g.key, ra_seconds: g.ra_seconds })), everything: true },
    { onSuccess: () => setConfirmAll(false) });
  const state = usePlayState();
  const s = stats.data;
  const st = state.data;
  const limit = st?.settings.alert_enabled ? st.settings.alert_minutes * 60 : null;
  const status = useStatus();

  // Bibliothèque jamais lue : les journaux de la console n'auraient ni jaquette ni fiche, on invite à synchroniser.
  if (status.data && !status.data.synced) return (
    <div className="page playtime">
      <PageHeader title={t("playtime.title")} lead={t("playtime.lead")} />
      <Empty title={t("dashboard.notSynced")}>
        <p>{t("playtime.notSynced")}</p>
        <Link to="/" className="button">{t("playtime.toSync")}</Link>
      </Empty>
    </div>
  );

  return (
    <div className="page playtime">
      <PageHeader title={t("playtime.title")} lead={t("playtime.lead")}>
        <Link to="/parametres/temps-de-jeu" className="button"><SettingsIcon size={16} aria-hidden /> {t("playtime.setLimit")}</Link>
      </PageHeader>

      <section className="block playtime__period" aria-labelledby="period-h">
        <h2 id="period-h"><CalendarRange size={18} aria-hidden /> {t("playtime.period.title")}</h2>
        <div className="playtime__period-fields">
          <label className="field">
            <span className="field__label">{t("playtime.period.from")}</span>
            <input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="field">
            <span className="field__label">{t("playtime.period.to")}</span>
            <input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
          </label>
          {(from || to) && (
            <button type="button" className="link-button" onClick={() => { setFrom(""); setTo(""); }}>
              <X size={14} aria-hidden /> {t("playtime.period.clear")}
            </button>
          )}
        </div>
        {period ? <p className="muted">{t("playtime.period.note")}</p>
          : (from || to) && <p className="muted">{t("playtime.period.incomplete")}</p>}
      </section>

      {stats.isPending ? <Spinner label={t("common.loading")} /> : stats.isError ? <ErrorNotice error={stats.error} /> : s && (
        <>
          <div className="stat-tiles">
            <TodayTile seconds={st?.today_seconds ?? s.today_seconds} limit={limit} scope={st?.settings.alert_scope ?? "session"} />
            <div className="stat-tile">
              <p className="stat-tile__label">{t("playtime.week")}</p>
              <p className="stat-tile__value num">{dur(s.week_seconds)}</p>
            </div>
            <div className="stat-tile">
              <p className="stat-tile__label">{period ? t("playtime.periodTotal") : t("playtime.total")}</p>
              <p className="stat-tile__value num">{dur(s.total_seconds)}</p>
              <p className="stat-tile__sub muted">{t("playtime.gamesCount", { count: s.games.length })}</p>
            </div>
          </div>

          {st?.playing && (
            <section className="block now-session" aria-label={t("playtime.current")}>
              <span className="led led--live" aria-hidden />
              <p><strong>{st.title}</strong> · {t("playtime.sessionFor", { d: dur(st.session_seconds) })}</p>
              {limit != null && st.settings.alert_scope === "session" && (
                <LimitGauge value={st.session_seconds} limit={limit} />
              )}
            </section>
          )}

          <section className="block" aria-labelledby="days-h">
            <h2 id="days-h">{period
              ? t("playtime.period.days", { from: fmtDate(period.start), to: fmtDate(period.end) })
              : t("playtime.daysTitle")}</h2>
            <DaysChart days={s.days} limit={st?.settings.alert_scope === "day" ? limit : null} />
          </section>

          <section className="block" aria-labelledby="games-h">
            <h2 id="games-h">{t("playtime.gamesTitle")}</h2>
            {s.games.length === 0 ? <Empty title={t("playtime.noGames")}><p>{t("playtime.noGamesBody")}</p></Empty> : (
              <GamesChart games={s.games.slice(0, 12)} onReset={resetGame} busy={reset.isPending} />
            )}
            {!s.retroarch_available && <p className="muted">{t("playtime.raUnavailable")}</p>}
          </section>

          <section className="block" aria-labelledby="hist-h">
            <h2 id="hist-h"><Clock size={18} aria-hidden /> {t("playtime.historyTitle")}</h2>
            {s.sessions.length === 0 ? <p className="muted">{t("playtime.noSessions")}</p> : (
              <ul className="sessions">
                {s.sessions.map((x) => (
                  <li key={x.id} className="session">
                    {x.game ? <Cover game={x.game} className="session__cover" /> : <span className="session__cover session__cover--empty" aria-hidden />}
                    <span className="session__title">{x.title}{(x.game?.platform.code ?? x.platform) && <> <ConsoleBadge code={x.game?.platform.code ?? x.platform!} label={x.game?.platform.label} /></>}</span>
                    <span className="num muted">{dateTime(x.started_at)}</span>
                    <span className="num session__dur">{dur(x.seconds)}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="muted playtime__note">{t("playtime.sourcesNote")}</p>
          </section>

          <section className="block playtime__danger" aria-labelledby="erase-h">
            <h2 id="erase-h"><Trash2 size={18} aria-hidden /> {t("playtime.erase.title")}</h2>
            <p className="muted">{t("playtime.erase.lead")}</p>
            {confirmAll ? (
              <div className="playtime__confirm" role="group" aria-label={t("playtime.erase.confirm")}>
                <strong>{t("playtime.erase.confirm")}</strong>
                <button type="button" className="button button--danger button--small" disabled={reset.isPending} onClick={resetAll}>
                  {t("playtime.erase.yes")}
                </button>
                <button type="button" className="button button--small" onClick={() => setConfirmAll(false)}>{t("playtime.erase.no")}</button>
              </div>
            ) : (
              <button type="button" className="button button--danger" disabled={!base.data || base.data.games.length === 0}
                onClick={() => setConfirmAll(true)}>
                <Trash2 size={16} aria-hidden /> {t("playtime.erase.all")}
              </button>
            )}
            {reset.isError && <ErrorNotice error={reset.error} />}
          </section>
        </>
      )}
    </div>
  );
}

function TodayTile({ seconds, limit, scope }: { seconds: number; limit: number | null; scope: string }) {
  const t = useT();
  const dur = useDuration();
  return (
    <div className="stat-tile stat-tile--main">
      <p className="stat-tile__label"><Hourglass size={14} aria-hidden /> {t("playtime.today")}</p>
      <p className="stat-tile__value num">{dur(seconds)}</p>
      {limit != null && scope === "day" ? <LimitGauge value={seconds} limit={limit} /> : (
        <p className="stat-tile__sub muted">{limit != null ? t("playtime.limitPerSession", { d: dur(limit) }) : t("playtime.noLimit")}</p>
      )}
    </div>
  );
}

/** Jauge vers la limite : couleur d'accent, puis couleur d'alerte (avec texte) une fois la limite atteinte. */
export function LimitGauge({ value, limit }: { value: number; limit: number }) {
  const t = useT();
  const dur = useDuration();
  const over = value >= limit;
  const pct = Math.min(100, (value / limit) * 100);
  return (
    <div className={`limit-gauge ${over ? "is-over" : ""}`}>
      <div className="limit-gauge__bar" role="meter" aria-valuemin={0} aria-valuemax={limit} aria-valuenow={value}
        aria-label={t("playtime.limitAria", { v: dur(value), l: dur(limit) })}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <p className="limit-gauge__text num">
        {over ? t("playtime.limitReached", { l: dur(limit) }) : t("playtime.limitLeft", { d: dur(limit - value), l: dur(limit) })}
      </p>
    </div>
  );
}

function DaysChart({ days, limit }: { days: PlayStats["days"]; limit: number | null }) {
  const t = useT();
  const dur = useDuration();
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(60 * 30, limit ?? 0, ...days.map((d) => d.seconds));
  const fmtDay = new Intl.DateTimeFormat(locale(), { weekday: "short", day: "numeric" });
  const fmtLong = new Intl.DateTimeFormat(locale(), { weekday: "long", day: "numeric", month: "long" });
  const total = days.reduce((n, d) => n + d.seconds, 0);
  if (total === 0) return <p className="muted">{t("playtime.noDays")}</p>;
  return (
    <div className="days-chart">
      <div className="days-chart__plot" onMouseLeave={() => setHover(null)}>
        {limit != null && (
          <div className="days-chart__limit" style={{ bottom: `${(limit / max) * 100}%` }}>
            <span>{t("playtime.limitLine", { l: dur(limit) })}</span>
          </div>
        )}
        {days.map((d, i) => {
          const date = new Date(`${d.date}T12:00:00`);
          return (
            <button key={d.date} type="button" className={`days-chart__col ${hover === i ? "is-hover" : ""}`}
              onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}
              aria-label={`${fmtLong.format(date)} : ${dur(d.seconds)}`}>
              <span className={`days-chart__bar ${limit != null && d.seconds >= limit ? "is-over" : ""}`}
                style={{ height: `${(d.seconds / max) * 100}%` }} />
              {hover === i && (
                <span className="chart-tip" role="tooltip">
                  <strong>{fmtLong.format(date)}</strong><br />{dur(d.seconds)}
                  {limit != null && d.seconds >= limit && <><br />{t("playtime.overLimit")}</>}
                </span>
              )}
            </button>
          );
        })}
      </div>
      <div className="days-chart__axis" aria-hidden>
        {days.map((d, i) => (
          <span key={d.date}>{i % 2 === days.length % 2 ? fmtDay.format(new Date(`${d.date}T12:00:00`)) : ""}</span>
        ))}
      </div>
      {limit != null && (
        <p className="days-chart__legend">
          <span className="days-chart__key" aria-hidden /> {t("playtime.legendUnder")}
          <span className="days-chart__key is-over" aria-hidden /> {t("playtime.overLimit")}
        </p>
      )}
    </div>
  );
}

function GamesChart({ games, onReset, busy }: { games: PlayStats["games"]; onReset: (key: string) => void; busy: boolean }) {
  const t = useT();
  const dur = useDuration();
  const [confirm, setConfirm] = useState<string | null>(null);
  const max = Math.max(1, ...games.map((g) => g.seconds));
  return (
    <ul className="games-chart">
      {games.map((g, i) => (
        <li key={`${g.title}-${i}`} className="games-chart__row">
          {g.game ? <Cover game={g.game} className="games-chart__cover" /> : <span className="games-chart__cover session__cover--empty" aria-hidden />}
          <div className="games-chart__main">
            <p className="games-chart__title">
              {g.title}
              {" "}{(g.game?.platform.code ?? g.platform)
                ? <ConsoleBadge code={g.game?.platform.code ?? g.platform!} label={g.game?.platform.label} />
                : <span className="muted"> · {t("playtime.unknownConsole")}</span>}
            </p>
            <div className="games-chart__track" aria-hidden><span style={{ width: `${(g.seconds / max) * 100}%` }} /></div>
            <p className="muted games-chart__sub">
              {g.last_played ? t("playtime.lastPlayed", { at: dateTime(g.last_played) })
                : g.last_played_console ? t("playtime.lastPlayedConsole", { at: g.last_played_console }) : ""}
              {g.sessions > 0 && ` · ${t("playtime.sessions", { count: g.sessions })}`}
            </p>
          </div>
          <span className="games-chart__value num">{dur(g.seconds)}</span>
          {confirm === g.key ? (
            <span className="games-chart__confirm" role="group" aria-label={t("playtime.erase.gameConfirm", { title: g.title })}>
              <button type="button" className="button button--danger button--small" disabled={busy}
                onClick={() => { onReset(g.key); setConfirm(null); }}>{t("playtime.erase.yes")}</button>
              <button type="button" className="button button--small" onClick={() => setConfirm(null)}>{t("playtime.erase.no")}</button>
            </span>
          ) : (
            <button type="button" className="icon-button" aria-label={t("playtime.erase.game", { title: g.title })}
              title={t("playtime.erase.game", { title: g.title })} onClick={() => setConfirm(g.key)}>
              <Trash2 size={15} aria-hidden />
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
