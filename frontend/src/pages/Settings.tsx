import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, BookOpen, Bot, Gamepad2, Info, Play, Volume2, CalendarClock, ExternalLink, CheckCircle2, Cpu, Hourglass, KeyRound, Loader2, MinusCircle, Plug, Languages, RefreshCw, ShieldCheck, Sparkles, Video, XCircle } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, NavLink, useParams } from "react-router-dom";

import { api, ApiError, type Capabilities, type DeviceSettings, type HostKey, type PlaySettings, type Settings } from "../api/client";
import {
  useDetectSystem, useDeviceStatus, usePlaySettings, useSavePlaySettings, useSettings, useSystem, useSystems, useYoutubeSettings,
} from "../api/queries";
import { GitHubStar } from "../components/GitHubStar";
import { LlmPanel } from "../components/LlmPanel";
import { SecretInput } from "../components/SecretInput";
import { ErrorNotice, hintFor, Meter, PageHeader, Spinner } from "../components/ui";
import logo480 from "../assets/brand/romkade-manager-logo-480.webp";
import { CREDITS } from "../lib/credits";
import { APP_VERSION } from "../version";
import { dateTime } from "../lib/format";
import { getLang, locale, t, useT } from "../i18n";
import { has } from "../i18n/core";

/** Onglets de la page, chacun à sa propre adresse (/parametres/<slug>) pour y mener par un lien. */
const TABS = [
  { slug: "", label: "settings.tab.connection", icon: Plug },
  { slug: "test", label: "settings.tab.test", icon: Activity },
  { slug: "systeme", label: "settings.tab.system", icon: Cpu },
  { slug: "temps-de-jeu", label: "settings.tab.playtime", icon: Hourglass },
  { slug: "videos", label: "settings.tab.videos", icon: Video },
  { slug: "ia", label: "settings.tab.ai", icon: Bot },
  { slug: "descriptions", label: "settings.tab.descriptions", icon: Languages },
  { slug: "a-propos", label: "legal.about.title", icon: Info },
] as const;

export function SettingsPage() {
  const t = useT();
  const settings = useSettings();
  const { tab: raw = "" } = useParams();
  const tab = raw === "credits" ? "a-propos" : raw;  // ancienne adresse de Sources et crédits
  const current = TABS.find((x) => x.slug === tab) ? tab : "";
  if (settings.isPending) return <div className="page"><Spinner label={t("common.loading")} /></div>;
  if (settings.isError) return <div className="page"><ErrorNotice error={settings.error} /></div>;
  return (
    <div className="page settings">
      <PageHeader title={t("common.nav.settings")} lead={t("settings.lead")} />
      <nav className="subnav" aria-label={t("settings.tab.label")}>
        {TABS.map(({ slug, label, icon: Icon }) => (
          <NavLink key={slug} to={slug ? `/parametres/${slug}` : "/parametres"} end
            className={() => `subnav__item ${current === slug ? "is-active" : ""}`}
            aria-current={current === slug ? "page" : undefined}>
            <Icon size={16} aria-hidden /> {t(label)}
          </NavLink>
        ))}
      </nav>
      {current === "" && (
        <>
          <ConnectionSteps settings={settings.data} />
          <ConnectionForm initial={settings.data} hasPassword={settings.data.has_password} />
          <HostKeyPanel trusted={settings.data.host_key_trusted} host={settings.data.host} />
        </>
      )}
      {current === "test" && <TestPanel />}
      {current === "systeme" && (
        <>
          <CapabilitiesPanel />
          <SystemPanel settings={settings.data} />
          <ClockPanel />
        </>
      )}
      {current === "temps-de-jeu" && <PlaytimePanel />}
      {current === "videos" && <YouTubePanel />}
      {current === "ia" && <LlmPanel />}
      {current === "descriptions" && <DescriptionsPanel />}
      {current === "a-propos" && <><AboutPanel /><CreditsPanel /></>}
    </div>
  );
}

function fieldErrors(err: unknown): Record<string, string> {
  if (!(err instanceof ApiError) || err.code !== "validation_error") return {};
  const out: Record<string, string> = {};
  for (const e of (err.details.errors as { loc: string[]; msg: string }[]) ?? []) out[e.loc[e.loc.length - 1]!] = e.msg;
  return out;
}

/**
 * Mise en route en trois étapes : 1. la console (adresse, utilisateur, mot de passe ou clé SSH) ; 2. son identité
 * (empreinte de sa clé, approuvée une fois) ; 3. le test de connexion. Chaque étape faite est cochée.
 */
function ConnectionSteps({ settings }: { settings: Settings }) {
  const t = useT();
  const auth = settings.auth_method === "password" ? settings.has_password : !!settings.key_path;
  const steps = [
    { n: 1, label: t("settings.steps.console"), done: !!settings.host && auth, href: "#conn-h" },
    { n: 2, label: t("settings.steps.identity"), done: settings.host_key_trusted, href: "#hk" },
    { n: 3, label: t("settings.steps.test"), done: false, to: "/parametres/test" },
  ];
  const current = steps.find((s) => !s.done)?.n ?? 3;
  return (
    <nav className="steps" aria-label={t("settings.steps.label")}>
      <ol>
        {steps.map((s) => {
          const body = (
            <>
              <span className="steps__num" aria-hidden>{s.done ? <CheckCircle2 size={16} /> : s.n}</span>
              <span>{s.label}</span>
              <span className="visually-hidden"> — {t(s.done ? "settings.steps.done" : s.n === current ? "settings.steps.current" : "settings.steps.todo")}</span>
            </>
          );
          const cls = `steps__item ${s.done ? "is-done" : ""} ${s.n === current ? "is-current" : ""}`;
          return (
            <li key={s.n}>
              {s.to ? <Link to={s.to} className={cls}>{body}</Link> : <a href={s.href} className={cls}>{body}</a>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Étape 1 : la console. Le choix d'authentification affiche son propre champ (mot de passe ou clé SSH). */
function ConnectionForm({ initial, hasPassword }: { initial: DeviceSettings; hasPassword: boolean }) {
  const t = useT();
  const qc = useQueryClient();
  const [form, setForm] = useState<DeviceSettings>(initial);
  const [pw, setPw] = useState("");
  useEffect(() => setForm(initial), [initial]);
  const dirty = JSON.stringify(form) !== JSON.stringify(initial);
  const withPassword = form.auth_method === "password" && !!pw;
  const save = useMutation({
    // Les réglages d'abord : le mot de passe est rangé dans le trousseau pour l'utilisateur et l'adresse enregistrés.
    mutationFn: async () => {
      if (dirty) await api.saveSettings(form);
      if (withPassword) await api.savePassword(pw);
    },
    onSuccess: () => {
      setPw("");
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["device-status"] });
      qc.invalidateQueries({ queryKey: ["system"] });
    },
  });
  const errs = fieldErrors(save.error);
  const set = <K extends keyof DeviceSettings>(k: K, v: DeviceSettings[K]) => setForm((f) => ({ ...f, [k]: v }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };

  return (
    <form className="block form" onSubmit={submit} aria-labelledby="conn-h" noValidate>
      <h2 id="conn-h"><span className="step-badge" aria-hidden>1</span> {t("settings.conn.title")}</h2>
      <p className="muted block__lead">{t("settings.conn.lead")}</p>
      <div className="form__grid">
        <Field id="host" label={t("settings.conn.host")} error={errs.host} hint={t("settings.conn.hostHint")}>
          <input id="host" value={form.host} onChange={(e) => set("host", e.target.value)} autoComplete="off" spellCheck={false} />
        </Field>
        <Field id="port" label={t("settings.conn.port")} error={errs.port}>
          <input id="port" type="number" min={1} max={65535} value={form.port} onChange={(e) => set("port", Number(e.target.value))} />
        </Field>
        <Field id="username" label={t("settings.conn.username")} error={errs.username}>
          <input id="username" value={form.username} onChange={(e) => set("username", e.target.value)} autoComplete="off" spellCheck={false} />
        </Field>
        <Field id="roms_root" label={t("settings.conn.romsRoot")} error={errs.roms_root} hint={t("settings.conn.romsRootHint")}>
          <input id="roms_root" value={form.roms_root} onChange={(e) => set("roms_root", e.target.value)} spellCheck={false} />
        </Field>
      </div>

      <fieldset className="auth-choice">
        <legend>{t("settings.conn.auth")}</legend>
        <div className="auth-choice__options" role="radiogroup">
          {(["password", "key"] as const).map((m) => (
            <label key={m} className={`auth-choice__option ${form.auth_method === m ? "is-on" : ""}`}>
              <input type="radio" name="auth_method" value={m} checked={form.auth_method === m} onChange={() => set("auth_method", m)} />
              {m === "password" ? <KeyRound size={16} aria-hidden /> : <ShieldCheck size={16} aria-hidden />}
              {t(m === "password" ? "settings.conn.authPassword" : "settings.conn.authKey")}
            </label>
          ))}
        </div>
        <div className="auth-choice__panel">
          {form.auth_method === "password" ? (
            <>
              <p className="muted">{hasPassword ? t("settings.pw.saved") : t("settings.pw.none")}</p>
              <div className="field">
                <label htmlFor="pw">{hasPassword ? t("settings.pw.replace") : t("settings.pw.label")}</label>
                <SecretInput id="pw" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" />
                <p className="field__hint">{t("settings.pw.hint")}</p>
              </div>
            </>
          ) : (
            <Field id="key_path" label={t("settings.conn.keyPath")} error={errs.key_path} hint={t("settings.conn.keyHint")}>
              <input id="key_path" value={form.key_path ?? ""} onChange={(e) => set("key_path", e.target.value || null)} placeholder="/Users/…/.ssh/id_ed25519" spellCheck={false} />
            </Field>
          )}
        </div>
      </fieldset>

      <div className="form__actions">
        <button type="submit" className="button button--primary" disabled={save.isPending || (!dirty && !withPassword)}>{t("settings.save")}</button>
        {save.isSuccess && !dirty && <span className="ok-text" role="status"><CheckCircle2 size={16} aria-hidden /> {t("settings.saved")}</span>}
      </div>
      {save.isError && !Object.keys(errs).length && <ErrorNotice error={save.error} />}
    </form>
  );
}

/** Capacités du système, regroupées par usage ; chacune mène à la page où elle sert. */
const CAP_GROUPS: { id: string; icon: typeof Gamepad2; caps: { key: keyof Capabilities; to?: string }[] }[] = [
  { id: "games", icon: Play, caps: [{ key: "launch", to: "/bibliotheque" }, { key: "quit" }, { key: "resume_slot", to: "/sauvegardes" },
    { key: "save_state", to: "/sauvegardes" }] },
  { id: "sound", icon: Volume2, caps: [{ key: "volume" }, { key: "bluetooth_audio", to: "/bluetooth" }] },
  { id: "players", icon: Gamepad2, caps: [{ key: "players", to: "/manettes" }, { key: "bluetooth", to: "/bluetooth" }] },
  { id: "playtime", icon: Hourglass, caps: [{ key: "retroarch_logs", to: "/temps-de-jeu" }] },
];

function CapsGroups({ caps }: { caps: Capabilities }) {
  const t = useT();
  return (
    <div className="caps-groups">
      {CAP_GROUPS.map(({ id, icon: Icon, caps: items }) => (
        <div key={id} className="caps-group">
          <h3><Icon size={16} aria-hidden /> {t(`settings.system.group.${id}`)}</h3>
          <ul className="caps">
            {items.map(({ key, to }) => {
              const on = caps[key];
              const label = t(`settings.system.cap.${key}`);
              return (
                <li key={key} className={on ? "caps__yes" : "caps__no"}>
                  {on ? <CheckCircle2 size={16} aria-hidden /> : <MinusCircle size={16} aria-hidden />}
                  {on && to ? <Link to={to}>{label}</Link> : <span>{label}</span>}
                  <span className="visually-hidden"> : {on ? t("settings.system.yes") : t("settings.system.no")}</span>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

/** Ce que l'application sait faire avec la console branchée : mis en avant en haut de l'onglet Système. */
function CapabilitiesPanel() {
  const t = useT();
  const system = useSystem();
  const online = useDeviceStatus().data?.connected === true;
  const info = system.data;
  return (
    <section className="block caps-panel" aria-labelledby="caps-h">
      <h2 id="caps-h">{t("settings.system.capsPanelTitle")}</h2>
      {info ? (
        <>
          <p className={`caps-panel__state ${online ? "is-online" : "is-offline"}`}>
            <span className="status-dot" aria-hidden />
            <span>{t(online ? "settings.system.capsOnline" : "settings.system.capsOffline", { name: info.profile.label })}</span>
          </p>
          <CapsGroups caps={info.capabilities} />
          <p className="muted">{t("settings.system.capsMissing")}</p>
        </>
      ) : system.isPending ? <Spinner label={t("common.loading")} /> : <p className="muted">{t("settings.system.notDetected")}</p>}
    </section>
  );
}

/** Firmware de la console : détecté par SSH (lecture seule) ou choisi ; ce que Game Manager sait y faire. */
function SystemPanel({ settings }: { settings: Settings }) {
  const t = useT();
  const qc = useQueryClient();
  const system = useSystem();
  const systems = useSystems();
  const detect = useDetectSystem();
  const [choice, setChoice] = useState(settings.system);
  useEffect(() => setChoice(settings.system), [settings.system]);
  const save = useMutation({
    mutationFn: (s: DeviceSettings) => api.saveSettings(s),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["system"] });
    },
  });
  const info = system.data;
  const detected = info?.detected;
  const shown = choice === "auto" ? info?.profile : systems.data?.find((p) => p.id === choice);
  const caps = choice === settings.system ? info?.capabilities : shown?.capabilities;
  const root = detected?.suggested_roms_root;
  return (
    <section className="block form" aria-labelledby="sys-h">
      <h2 id="sys-h">{t("settings.system.title")}</h2>
      <p className="muted">{t("settings.system.lead")}</p>
      <div className="form__grid">
        <Field id="system" label={t("settings.system.choice")} wide>
          <select id="system" value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="auto">
              {detected ? t("settings.system.autoDetected", { name: detected.label }) : t("settings.system.auto")}
            </option>
            {(systems.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.label} ({p.status === "tested" ? t("settings.system.tested") : t("settings.system.experimental")})
              </option>
            ))}
          </select>
        </Field>
      </div>
      <p className="muted">
        {detected ? t("settings.system.detected", { name: detected.label }) : t("settings.system.notDetected")}
        {detected?.os_name && <> · {t("settings.system.os", { name: detected.os_name })}</>}
      </p>
      {shown?.notes && <p className="muted">{shown.notes}</p>}
      {shown?.status === "experimental" && <p className="text-warning">{t("settings.system.experimentalNote")}</p>}
      {root && root !== settings.roms_root && (
        <p>
          {t("settings.system.rootDiffers", { path: root, current: settings.roms_root })}{" "}
          <button type="button" className="button button--small" disabled={save.isPending}
            onClick={() => save.mutate({ ...settings, roms_root: root })}>
            {t("settings.system.useRoot", { path: root })}
          </button>
        </p>
      )}
      {caps && choice !== settings.system && shown && (
        <>
          <h3>{t("settings.system.capsPreview", { name: shown.label })}</h3>
          <CapsGroups caps={caps} />
        </>
      )}
      <div className="form__actions">
        <button type="button" className="button button--primary" disabled={save.isPending || choice === settings.system}
          onClick={() => save.mutate({ ...settings, system: choice })}>{t("settings.system.save")}</button>
        <button type="button" className="button" onClick={() => detect.mutate()} disabled={detect.isPending}>
          {detect.isPending ? t("settings.system.detecting") : t("settings.system.detect")}
        </button>
        {save.isSuccess && choice === settings.system && (
          <span className="ok-text" role="status"><CheckCircle2 size={16} aria-hidden /> {t("settings.system.saved")}</span>
        )}
      </div>
      {(detect.isError || save.isError) && <ErrorNotice error={detect.error ?? save.error} />}
    </section>
  );
}

function Field({ id, label, hint, error, wide, children }: { id: string; label: string; hint?: string; error?: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <div className={`field ${wide ? "field--wide" : ""} ${error ? "has-error" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {children}
      {error ? <p className="field__error">{error}</p> : hint ? <p className="field__hint">{hint}</p> : null}
    </div>
  );
}

/** Identité de la console (clé SSH). Pas encore approuvée (nouvelle console, nouvelle adresse) : l'empreinte est lue
 * tout de suite, il ne reste qu'à la comparer et à l'approuver ; « Paramètres#hk » (lien des erreurs) y amène. */
function HostKeyPanel({ trusted, host }: { trusted: boolean; host: string }) {
  const t = useT();
  const qc = useQueryClient();
  const [key, setKey] = useState<HostKey | null>(null);
  const read = useMutation({ mutationFn: api.hostKey, onSuccess: setKey });
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!trusted && host) { setKey(null); read.mutate(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trusted, host]);
  useEffect(() => {
    if (window.location.hash === "#hk") ref.current?.scrollIntoView({ block: "center" });
  }, []);
  const trust = useMutation({
    mutationFn: (fp: string) => api.trustHostKey(fp),
    onSuccess: (k) => {
      setKey(k);
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["device-status"] });
    },
  });
  return (
    <section id="hk" ref={ref} className={`block ${trusted ? "" : "block--attention"}`} aria-labelledby="hk-h">
      <h2 id="hk-h"><span className="step-badge" aria-hidden>2</span> {t("settings.hk.title")}</h2>
      <p className="muted block__lead">{t("settings.hk.lead")}</p>
      <p className={trusted ? "ok-text" : ""}>
        {trusted && <CheckCircle2 size={16} aria-hidden />} {trusted ? t("settings.hk.trusted") : host ? t("settings.hk.untrusted") : t("settings.hk.needHost")}
      </p>
      <button type="button" className="button" onClick={() => read.mutate()} disabled={read.isPending || !host}>
        {read.isPending ? t("settings.hk.reading") : t("settings.hk.read")}
      </button>
      {read.isError && <ErrorNotice error={read.error} />}
      {key && (
        <div className="fingerprint">
          <p className="muted">{key.algorithm}</p>
          <code className="break">{key.fingerprint}</code>
          {key.trusted ? (
            <p className="ok-text"><CheckCircle2 size={16} aria-hidden /> {t("settings.hk.approved")}</p>
          ) : (
            <>
              <p className="field__hint">
                {t("settings.hk.compareBefore")} <code>ssh-keyscan {key.host} 2&gt;/dev/null | ssh-keygen -lf -</code> {t("settings.hk.compareAfter")}
              </p>
              <button type="button" className="button button--primary" onClick={() => trust.mutate(key.fingerprint)} disabled={trust.isPending}>
                {t("settings.hk.approve")}
              </button>
            </>
          )}
          {trust.isError && <ErrorNotice error={trust.error} />}
        </div>
      )}
    </section>
  );
}

/** Fuseau du Mac (navigateur), envoyé à la console avec l'heure. */
const MAC_TZ = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || null; } catch { return null; } })();
/** Écart toléré entre la console et le Mac avant de proposer la mise à l'heure. */
const CLOCK_TOLERANCE_S = 120;

/** Date et heure de la console, comparées au Mac, avec « Mettre à l'heure du Mac ». */
function ClockPanel() {
  const t = useT();
  const qc = useQueryClient();
  const online = useDeviceStatus().data?.connected === true;
  const clock = useQuery({ queryKey: ["device-clock"], queryFn: api.clock, enabled: online, retry: false });
  const sync = useMutation({ mutationFn: () => api.syncClock(MAC_TZ), onSuccess: (d) => qc.setQueryData(["device-clock"], d) });
  const c = clock.data;
  const fmt = (epoch: number, timeZone?: string | null) => {
    try {
      return new Intl.DateTimeFormat(locale(), { dateStyle: "full", timeStyle: "medium", ...(timeZone ? { timeZone } : {}) })
        .format(new Date(epoch * 1000));
    } catch {
      return new Intl.DateTimeFormat(locale(), { dateStyle: "full", timeStyle: "medium", timeZone: "UTC" }).format(new Date(epoch * 1000));
    }
  };
  const drift = c ? Math.abs(c.drift_seconds) : 0;
  const late = c ? c.drift_seconds < 0 : false;
  const tzDiffers = c && MAC_TZ && c.timezone !== MAC_TZ;
  const ok = c && drift <= CLOCK_TOLERANCE_S && !tzDiffers;
  return (
    <section className="block" aria-labelledby="clock-h">
      <div className="block__head">
        <h2 id="clock-h"><CalendarClock size={18} aria-hidden /> {t("settings.clock.title")}</h2>
        <button type="button" className={`button ${c && !ok ? "button--primary" : ""}`} onClick={() => sync.mutate()}
          disabled={!online || sync.isPending}>
          {sync.isPending ? <Loader2 size={16} aria-hidden className="spin" /> : <RefreshCw size={16} aria-hidden />}
          {t("settings.clock.sync")}
        </button>
      </div>
      <p className="muted block__lead">{t("settings.clock.lead")}</p>
      {!online ? <p className="muted">{t("settings.clock.offline")}</p>
        : clock.isPending ? <Spinner label={t("common.loading")} />
        : clock.isError ? <ErrorNotice error={clock.error} />
        : c && (
          <dl className="facts facts--compact">
            <div><dt>{t("settings.clock.console")}</dt><dd>{fmt(c.console_epoch, c.timezone)}
              <span className="muted"> · {c.timezone ?? "?"}{c.utc_offset ? ` (UTC${c.utc_offset.slice(0, 3)}:${c.utc_offset.slice(3)})` : ""}</span></dd></div>
            <div><dt>{t("settings.clock.mac")}</dt><dd>{fmt(c.mac_epoch, MAC_TZ)}<span className="muted"> · {MAC_TZ ?? "?"}</span></dd></div>
            <div><dt>{t("settings.clock.gap")}</dt>
              <dd className={ok ? "ok-text" : "text-error"}>
                {ok ? <><CheckCircle2 size={16} aria-hidden /> {t("settings.clock.inSync")}</>
                  : drift > CLOCK_TOLERANCE_S ? t(late ? "settings.clock.late" : "settings.clock.ahead", { gap: gap(drift) })
                  : t("settings.clock.tzDiffers", { tz: MAC_TZ ?? "" })}
              </dd></div>
          </dl>
        )}
      {sync.isSuccess && ok && <p className="ok-text" role="status"><CheckCircle2 size={16} aria-hidden /> {t("settings.clock.done")}</p>}
      {sync.isError && <ErrorNotice error={sync.error} />}
    </section>
  );
}

/** Écart lisible : « 4 ans », « 3 h », « 12 min ». */
function gap(seconds: number): string {
  const units: [number, string][] = [[365 * 86400, "y"], [30 * 86400, "mo"], [86400, "d"], [3600, "h"], [60, "min"]];
  for (const [size, unit] of units) {
    if (seconds >= size) return t(`settings.clock.unit.${unit}`, { count: Math.floor(seconds / size) });
  }
  return t("settings.clock.unit.s", { count: seconds });
}

/** Diagnostic de la connexion, étape par étape (POST /api/device/diagnose). */
function TestPanel() {
  const t = useT();
  const test = useMutation({ mutationFn: api.diagnose });
  const r = test.data;
  const qc = useQueryClient();
  const run = () => test.mutate(undefined, { onSuccess: () => qc.invalidateQueries({ queryKey: ["device-status"] }) });
  return (
    <section className="block" aria-labelledby="test-h">
      <div className="block__head">
        <h2 id="test-h">{t("settings.test.title")}</h2>
        <button type="button" className="button" onClick={run} disabled={test.isPending}>
          {test.isPending ? <Loader2 size={16} aria-hidden className="spin" /> : <Activity size={16} aria-hidden />}
          {test.isPending ? t("settings.test.running") : t("settings.test.run")}
        </button>
      </div>
      <p className="muted block__lead">{t("settings.test.lead")}</p>
      {test.isError && <ErrorNotice error={test.error} title={t("settings.test.failed")} />}
      {r && (
        <>
          <p className={r.ok ? "ok-text" : "text-error"} role="status">
            {r.ok ? <CheckCircle2 size={16} aria-hidden /> : <XCircle size={16} aria-hidden />}{" "}
            {r.ok ? t("settings.test.allOk", { host: r.host }) : t("settings.test.someFailed")}
          </p>
          <ol className="diag">
            {r.steps.map((step) => (
              <li key={step.id} className={`diag__step is-${step.status}`}>
                <span className="diag__icon" aria-hidden>
                  {step.status === "ok" ? <CheckCircle2 size={18} /> : step.status === "failed" ? <XCircle size={18} /> : <MinusCircle size={18} />}
                </span>
                <span className="diag__name">{t(`settings.test.step.${step.id}`, { port: r.port })}</span>
                <span className="diag__status">
                  {t(`settings.test.status.${step.status}`)}{step.ms != null && <span className="num muted"> · {Math.round(step.ms)} ms</span>}
                </span>
                {step.detail && <code className="diag__detail">{step.detail}</code>}
                {step.status === "failed" && (
                  <div className="diag__error">
                    <p>{step.code && hasError(step.code) ? t(`common.error.${step.code}`) : step.message}</p>
                    {step.code && hintFor(step.code) && <p className="muted">{hintFor(step.code)}</p>}
                  </div>
                )}
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

/** Message traduit du code d'erreur, s'il existe dans la langue choisie (sinon celui du serveur). */
const hasError = (code: string) => getLang() !== "fr" && has(`common.error.${code}`);

/**
 * Descriptions des jeux en français, anglais et espagnol, rédigées ou traduites par Claude : clé d'API Anthropic
 * (trousseau), avancement, lancement d'un lot (API Batches) et suivi. Voir backend app/services/descriptions.py.
 */
function DescriptionsPanel() {
  const t = useT();
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["descriptions"], queryFn: api.descriptions,
    refetchInterval: (q) => (q.state.data?.batches.some((b) => !b.imported) ? 60_000 : false) });
  const start = useMutation({ mutationFn: api.startDescriptions, onSuccess: (d) => qc.setQueryData(["descriptions"], d) });
  const st = status.data;
  const running = st?.batches.find((b) => !b.imported);
  return (
    <>
      <section className="block" aria-labelledby="desc-h">
        <div className="block__head">
          <h2 id="desc-h"><Languages size={18} aria-hidden /> {t("settings.desc.title")}</h2>
        </div>
        <p className="muted block__lead">{t("settings.desc.lead")}</p>
        {status.isPending ? <Spinner label={t("common.loading")} /> : status.isError ? <ErrorNotice error={status.error} /> : st && (
          <>
            <Meter value={st.complete} max={Math.max(st.games, 1)} label={t("settings.desc.progress", { done: st.complete, total: st.games })} />
            <p>{t("settings.desc.progress", { done: st.complete, total: st.games })}</p>
            {running ? (
              <p className="desc-run" role="status">
                <Loader2 size={16} aria-hidden className="spin" />{" "}
                {t(running.batch_id.startsWith("direct-") ? "settings.desc.runningDirect" : "settings.desc.running",
                  { done: running.succeeded + running.errored, total: running.games })}
              </p>
            ) : st.pending > 0 && (
              <div className="form__actions">
                <button type="button" className="button button--primary" disabled={!st.credentials || start.isPending}
                  onClick={() => start.mutate()}>
                  {start.isPending ? <Loader2 size={16} aria-hidden className="spin" /> : <Sparkles size={16} aria-hidden />}
                  {st.estimate_usd != null
                    ? t("settings.desc.start", { count: st.pending, cost: st.estimate_usd.toFixed(0) })
                    : t("settings.desc.startFree", { count: st.pending })}
                </button>
                {!st.credentials && <Link to="/parametres/ia" className="muted">{t("settings.desc.needKey")}</Link>}
              </div>
            )}
            <p className="muted">
              {st.provider
                ? t(st.batch ? "settings.desc.modelBatch" : st.local ? "settings.desc.modelLocal" : "settings.desc.modelDirect",
                  { provider: t(`settings.ai.provider.${st.provider}`), model: st.model ?? "?" })
                : t("settings.desc.noAi")}{" "}
              <Link to="/parametres/ia">{t(st.provider ? "settings.desc.changeAi" : "settings.desc.connectAi")}</Link>
            </p>
            {start.isError && <ErrorNotice error={start.error} />}
            {st.batches.length > 0 && (
              <ul className="desc-batches">
                {st.batches.map((b) => (
                  <li key={b.batch_id}>
                    <span>{dateTime(b.created_at)}</span>
                    <span className="muted">{t("settings.desc.batch", { games: b.games })}</span>
                    <span>{b.imported
                      ? t("settings.desc.imported", { texts: Number(b.result?.texts ?? 0), games: Number(b.result?.games ?? 0) })
                      : t("settings.desc.inProgress", { done: b.succeeded + b.errored, total: b.games })}</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>

    </>
  );
}

function YouTubePanel() {
  const t = useT();
  const qc = useQueryClient();
  const yt = useYoutubeSettings();
  const [key, setKey] = useState("");
  const done = () => {
    setKey("");
    qc.invalidateQueries({ queryKey: ["youtube-settings"] });
    qc.invalidateQueries({ queryKey: ["game-video"] });
  };
  const save = useMutation({ mutationFn: api.saveYoutubeKey, onSuccess: done });
  const remove = useMutation({ mutationFn: api.deleteYoutubeKey, onSuccess: done });
  const configured = yt.data?.configured;
  return (
    <form className="block form" aria-labelledby="yt-h" onSubmit={(e) => { e.preventDefault(); if (key.trim()) save.mutate(key.trim()); }}>
      <h2 id="yt-h"><Video size={18} aria-hidden /> {t("settings.yt.title")}</h2>
      <p className="muted block__lead">
        {t("settings.yt.leadBefore")}{" "}
        <a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com"
        target="_blank" rel="noreferrer noopener">console.cloud.google.com</a>
        {t("settings.yt.leadAfter")}
      </p>
      <p className="muted">
        {yt.isPending ? " " : configured ? t("settings.yt.saved") : t("settings.yt.none")}
      </p>
      <div className="field">
        <label htmlFor="ytkey">{configured ? t("settings.yt.replace") : t("settings.yt.label")}</label>
        <SecretInput id="ytkey" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" spellCheck={false} />
      </div>
      <div className="form__actions">
        <button type="submit" className="button" disabled={!key.trim() || save.isPending}>{t("settings.saveKeychain")}</button>
        {configured && (
          <button type="button" className="link-button" onClick={() => remove.mutate()} disabled={remove.isPending}>{t("settings.yt.remove")}</button>
        )}
        {save.isSuccess && <span className="ok-text" role="status"><CheckCircle2 size={16} aria-hidden /> {t("settings.savedF")}</span>}
      </div>
      {(save.isError || remove.isError) && <ErrorNotice error={save.error ?? remove.error} />}
    </form>
  );
}

/** Limite de temps de jeu : l'alerte s'affiche dans Game Manager et, si coché, sur l'écran de la console. */
function PlaytimePanel() {
  const t = useT();
  const q = usePlaySettings();
  const save = useSavePlaySettings();
  const [form, setForm] = useState<PlaySettings | null>(null);
  useEffect(() => { if (q.data) setForm(q.data); }, [q.data]);
  useEffect(() => {
    if (window.location.hash === "#temps-de-jeu") document.getElementById("temps-de-jeu")?.scrollIntoView({ block: "start" });
  }, [form != null]);
  if (!form) return null;
  const set = <K extends keyof PlaySettings>(k: K, v: PlaySettings[K]) => setForm({ ...form, [k]: v });
  const hours = Math.floor(form.alert_minutes / 60);
  const minutes = form.alert_minutes % 60;
  const setDuration = (h: number, m: number) => set("alert_minutes", Math.min(24 * 60, Math.max(5, h * 60 + m)));
  const dirty = JSON.stringify(form) !== JSON.stringify(q.data);
  return (
    <form id="temps-de-jeu" className="block form" aria-labelledby="pt-h" onSubmit={(e) => { e.preventDefault(); save.mutate(form); }}>
      <h2 id="pt-h"><Hourglass size={18} aria-hidden /> {t("settings.playtime.title")}</h2>
      <p className="muted block__lead">{t("settings.playtime.lead")}</p>
      <label className="toggle-inline toggle-inline--block">
        <input type="checkbox" checked={form.alert_enabled} onChange={(e) => set("alert_enabled", e.target.checked)} />
        {t("settings.playtime.enable")}
      </label>
      <fieldset className="playtime-form" disabled={!form.alert_enabled}>
        <div className="field">
          <span className="field__label">{t("settings.playtime.after")}</span>
          <div className="duration-input">
            <input type="number" min={0} max={24} value={hours} aria-label={t("settings.playtime.hours")}
              onChange={(e) => setDuration(Number(e.target.value) || 0, minutes)} />
            <span>{t("settings.playtime.h")}</span>
            <input type="number" min={0} max={59} step={5} value={minutes} aria-label={t("settings.playtime.minutes")}
              onChange={(e) => setDuration(hours, Number(e.target.value) || 0)} />
            <span>{t("settings.playtime.min")}</span>
          </div>
          <div className="presets">
            {[60, 120, 180, 240].map((m) => (
              <button key={m} type="button" className={`chip ${form.alert_minutes === m ? "is-on" : ""}`} onClick={() => set("alert_minutes", m)}>
                {t("settings.playtime.preset", { h: String(m / 60) })}
              </button>
            ))}
          </div>
        </div>
        <div className="field">
          <span className="field__label">{t("settings.playtime.count")}</span>
          <label className="radio-row"><input type="radio" name="scope" checked={form.alert_scope === "session"} onChange={() => set("alert_scope", "session")} /> {t("settings.playtime.scopeSession")}</label>
          <label className="radio-row"><input type="radio" name="scope" checked={form.alert_scope === "day"} onChange={() => set("alert_scope", "day")} /> {t("settings.playtime.scopeDay")}</label>
        </div>
        <div className="field">
          <label htmlFor="pt-repeat" className="field__label">{t("settings.playtime.repeat")}</label>
          <select id="pt-repeat" value={form.repeat_minutes} onChange={(e) => set("repeat_minutes", Number(e.target.value))}>
            {[0, 15, 30, 60].map((m) => <option key={m} value={m}>{m === 0 ? t("settings.playtime.repeatNever") : t("settings.playtime.repeatEvery", { m: String(m) })}</option>)}
          </select>
        </div>
        <label className="toggle-inline toggle-inline--block">
          <input type="checkbox" checked={form.console_message} onChange={(e) => set("console_message", e.target.checked)} />
          {t("settings.playtime.onConsole")}
        </label>
      </fieldset>
      <div className="form__actions">
        <button type="submit" className="button button--primary" disabled={!dirty || save.isPending}>{t("settings.playtime.save")}</button>
        {save.isSuccess && !dirty && <span className="ok-text" role="status"><CheckCircle2 size={16} aria-hidden /> {t("settings.playtime.saved")}</span>}
      </div>
      {save.isError && <ErrorNotice error={save.error} />}
      <p className="muted">{t("settings.playtime.note")}</p>
    </form>
  );
}

/** À propos : logo, version, rappel des conditions d'utilisation. */
function AboutPanel() {
  const t = useT();
  return (
    <section className="block about" aria-labelledby="about-h">
      <h2 id="about-h" className="visually-hidden">{t("legal.about.title")}</h2>
      <img className="about__logo" src={logo480} width={320} height={71} alt="ROMKADE Manager" />
      <p className="about__version num">{t("legal.version", { version: APP_VERSION })}</p>
      <p>{t("legal.about.lead")}</p>
      <p className="muted">{t("legal.about.legal")} <Link to="/conditions" className="link">{t("legal.link")}</Link></p>
    </section>
  );
}

/** Sources et crédits : tout ce que l'application reprend d'ailleurs (données, images, services), avec un lien. */
function CreditsPanel() {
  const t = useT();
  return (
    <section className="block credits" aria-labelledby="credits-h">
      <h2 id="credits-h"><BookOpen size={18} aria-hidden /> {t("settings.credits.title")}</h2>
      <p className="muted">{t("settings.credits.lead")}</p>
      {CREDITS.map(({ group, items }) => (
        <div key={group} className="credits__group">
          <h3>{t(`settings.credits.group.${group}`)}</h3>
          <ul className="credits__list">
            {items.map((c) => (
              <li key={c.id}>
                <a href={c.url} target="_blank" rel="noreferrer noopener" className="link">
                  {c.name} <ExternalLink size={12} aria-hidden />
                </a>
                {c.license && <span className="credits__license">{c.license}</span>}
                <p className="muted">{t(`settings.credits.${c.id}`)}</p>
              </li>
            ))}
          </ul>
        </div>
      ))}
      <div className="credits__support">
        <p>{t("settings.credits.support")}</p>
        <GitHubStar />
      </div>
    </section>
  );
}
