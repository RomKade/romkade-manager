import type { Factor, OAuthGrant } from "@supabase/supabase-js";
import { useQueryClient } from "@tanstack/react-query";
import { AppWindow, ArrowRight, Bot, Check, CheckCircle2, Cloud, Copy, Gamepad2, KeyRound, Link2, LogOut, Mail, PlugZap, ShieldCheck, UserRound } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Navigate, NavLink, useParams } from "react-router-dom";

import { useDeviceStatus } from "../api/queries";
import { useAuth } from "../auth/AuthContext";
import { CodeInput, PasswordInput } from "../auth/AuthScreen";
import { ACCOUNT_TABS, accountPath } from "../auth/accountTabs";
import { CLOUD_URL, cloud, localAgent, type AgentStatus, type CloudConsole } from "../auth/cloud";
import { PasswordStrength, passwordValid } from "../auth/password";
import { supabase } from "../auth/supabase";
import { SubNav } from "../components/SubNav";
import { PageHeader } from "../components/ui";
import { locale, useT } from "../i18n";

/**
 * Mon compte ROMKADE : tout passe par Supabase depuis l'interface (profil, e-mail, mot de passe, double
 * authentification, applications connectées), sauf les consoles reliées et la suppression du compte (ROMKADE Cloud),
 * et la liaison de la console branchée (moteur local du Manager, qui installe l'agent ROMKADE).
 */

export function AccountPage() {
  const t = useT();
  translate = t as typeof translate;
  const { tab = "" } = useParams();
  // Console et assistants autorisés vivent désormais dans Paramètres > Pilotage à distance.
  if (["console", "consoles", "applications"].includes(tab)) return <Navigate to="/parametres/pilotage" replace />;
  const current = ACCOUNT_TABS.some((x) => x.slug === tab) ? tab : "";
  return (
    <div className="page account">
      <PageHeader title={t("account.title")} lead={t("account.lead")} />
      <SubNav label={t("account.tab.label")} active={current}>
        {ACCOUNT_TABS.map(({ slug, label, icon: Icon }) => (
          <NavLink key={slug} to={accountPath(slug)} end
            className={() => `subnav__item ${current === slug ? "is-active" : ""} ${slug === "zone-dangereuse" ? "subnav__item--danger" : ""}`}
            aria-current={current === slug ? "page" : undefined}>
            <Icon size={16} aria-hidden /> {t(label)}
          </NavLink>
        ))}
      </SubNav>
      <div className="account__tab">
        {current === "" && <><Profile /><EmailChange /></>}
        {current === "securite" && <><PasswordChange /><TwoFactor /><Sessions /></>}
        {current === "zone-dangereuse" && <DeleteAccount />}
      </div>
    </div>
  );
}

/* ---------- briques ---------- */

/**
 * Paramètres > Pilotage à distance : ChatGPT, Claude… pilotent la console par ROMKADE Cloud (serveur MCP). Trois
 * étapes : relier la console (app ROMKADE + clé), ajouter ROMKADE dans l'assistant (côté ChatGPT / Claude), et les
 * assistants autorisés. Rien à voir avec l'Assistant IA du Manager (Duke), réglé dans son propre onglet.
 */
export function RemoteControl() {
  const t = useT();
  translate = t as typeof translate;
  return (
    <div className="account__tab remote">
      <div className="remote__flow" aria-label={t("account.remote.flowLabel")}>
        <span className="remote__node"><Bot size={16} aria-hidden /> ChatGPT · Claude</span>
        <ArrowRight size={16} aria-hidden className="remote__arrow" />
        <span className="remote__node"><Cloud size={16} aria-hidden /> ROMKADE Cloud</span>
        <ArrowRight size={16} aria-hidden className="remote__arrow" />
        <span className="remote__node"><Gamepad2 size={16} aria-hidden /> {t("account.remote.yourConsole")}</span>
        <p className="muted small remote__example">{t("account.remote.example")}</p>
      </div>
      <Consoles />
      <AddToAssistant />
      <ConnectedApps />
    </div>
  );
}

function AddToAssistant() {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(CLOUD_URL); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { /* sélection manuelle */ }
  };
  return (
    <Block icon={<PlugZap size={18} aria-hidden />} title={t("account.remote.add.title")} lead={t("account.remote.add.lead")}>
      {/* Adresse du connecteur : un seul encart, lien et bouton « Copier » dedans. */}
      <div className={`copy-link ${copied ? "is-copied" : ""}`}>
        <Link2 size={18} aria-hidden className="copy-link__icon" />
        <input className="copy-link__url" readOnly value={CLOUD_URL} aria-label={t("account.remote.add.url")} onFocus={(e) => e.currentTarget.select()} />
        <button type="button" className="button button--small copy-link__btn" onClick={copy}>
          {copied ? <Check size={15} aria-hidden /> : <Copy size={15} aria-hidden />} {copied ? t("account.remote.add.copied") : t("account.remote.add.copy")}
        </button>
      </div>
      <div className="remote__howto">
        <div><strong>ChatGPT</strong><p className="muted small">{t("account.remote.add.chatgpt")}</p></div>
        <div><strong>Claude</strong><p className="muted small">{t("account.remote.add.claude")}</p></div>
        <div>
          <strong>Google Home</strong> <span className="account__badge account__badge--soon">{t("account.remote.add.googleSoon")}</span>
          <p className="muted small">{t("account.remote.add.google")}</p>
          <p className="small remote__say">{t("account.remote.add.googleSay")}</p>
        </div>
      </div>
      <p className="field__hint">{t("account.remote.add.then")}</p>
    </Block>
  );
}

function Block({ icon, title, lead, children, danger }: { icon?: ReactNode; title: string; lead?: string; children: ReactNode; danger?: boolean }) {
  return (
    <section className={`block account__block ${danger ? "account__block--danger" : ""}`}>
      <div className="block__head"><h2>{icon}{icon && " "}{title}</h2></div>
      {lead && <p className="muted account__lead">{lead}</p>}
      {children}
    </section>
  );
}

function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const run = async (work: () => Promise<string | void>) => {
    setBusy(true); setError(""); setDone("");
    try { const msg = await work(); if (msg) setDone(msg); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  return { busy, error, done, run, setError };
}

function Result({ a }: { a: ReturnType<typeof useAction> }) {
  if (a.error) return <p className="auth__notice auth__notice--err" role="alert">{a.error}</p>;
  if (a.done) return <p className="auth__notice auth__notice--ok" role="status">{a.done}</p>;
  return null;
}

/** Codes d'erreur de Supabase Auth traduits (sinon message générique, suivi du détail). */
const AUTH_ERRORS = ["same_password", "weak_password", "otp_expired", "otp_disabled", "email_exists", "user_already_exists",
  "email_address_invalid", "reauthentication_needed", "reauthentication_not_valid", "over_email_send_rate_limit",
  "over_request_rate_limit", "mfa_verification_failed", "insufficient_aal", "session_not_found", "validation_failed"];
let translate: (key: string, vars?: Record<string, string>) => string = (k) => k;
const fail = (error: { code?: string; message?: string } | null) => {
  if (!error) return;
  const code = error.code ?? "";
  if (AUTH_ERRORS.includes(code)) throw new Error(translate(`account.err.${code}`));
  if (/expired|invalid.*(otp|token|nonce)/i.test(error.message ?? "")) throw new Error(translate("account.err.otp_expired"));
  if (/different from the old/i.test(error.message ?? "")) throw new Error(translate("account.err.same_password"));
  throw new Error(translate("account.err.generic", { detail: error.message ?? String(error) }));
};
const date = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString(locale(), { dateStyle: "long" }) : "");

/* ---------- sections ---------- */

function Profile() {
  const t = useT();
  const { session } = useAuth();
  const meta = (session?.user.user_metadata ?? {}) as { name?: string };
  const [name, setName] = useState(meta.name ?? "");
  const a = useAction();
  return (
    <Block icon={<UserRound size={18} aria-hidden />} title={t("account.profile.title")}>
      <form className="field" onSubmit={(e: FormEvent) => { e.preventDefault();
        a.run(async () => { const { error } = await supabase.auth.updateUser({ data: { name: name.trim() } }); fail(error); return t("account.saved"); }); }}>
        <label htmlFor="acc-name">{t("account.profile.name")}</label>
        <div className="account__inline">
          <input id="acc-name" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} required />
          <button className="button button--primary" disabled={a.busy || !name.trim()}>{t("account.save")}</button>
        </div>
      </form>
      <p className="field__hint">{t("account.profile.since", { date: date(session?.user.created_at) })}</p>
      <Result a={a} />
    </Block>
  );
}

function EmailChange() {
  const t = useT();
  const { session } = useAuth();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const a = useAction();
  return (
    <Block icon={<Mail size={18} aria-hidden />} title={t("account.email.title")}>
      <p><span className="muted">{t("account.email.current")} : </span><strong>{session?.user.email}</strong></p>
      {!sent ? (
        <form className="field" onSubmit={(e: FormEvent) => { e.preventDefault();
          a.run(async () => { const { error } = await supabase.auth.updateUser({ email: email.trim() }); fail(error); setSent(true); return t("account.email.sent", { email: email.trim() }); }); }}>
          <label htmlFor="acc-email">{t("account.email.new")}</label>
          <div className="account__inline">
            <input id="acc-email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            <button className="button" disabled={a.busy || !email.includes("@")}>{t("account.sendCode")}</button>
          </div>
        </form>
      ) : (
        <form className="account__form" onSubmit={(e: FormEvent) => { e.preventDefault();
          a.run(async () => { const { error } = await supabase.auth.verifyOtp({ email: email.trim(), token: code, type: "email_change" }); fail(error);
            setSent(false); setCode(""); setEmail(""); return t("account.email.done"); }); }}>
          <CodeInput id="acc-email-code" value={code} onChange={setCode} compact />
          <div className="actions account__actions">
            <button className="button button--primary" disabled={a.busy || code.length !== 6}>{t("account.confirm")}</button>
            <button type="button" className="button" onClick={() => { setSent(false); setCode(""); }}>{t("account.cancel")}</button>
          </div>
        </form>
      )}
      <Result a={a} />
    </Block>
  );
}

function PasswordChange() {
  const t = useT();
  const { session } = useAuth();
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const a = useAction();
  return (
    <Block icon={<KeyRound size={18} aria-hidden />} title={t("account.password.title")} lead={t("account.password.lead")}>
      {!sent ? (
        <button className="button" disabled={a.busy} onClick={() => a.run(async () => {
          const { error } = await supabase.auth.reauthenticate(); fail(error); setSent(true);
          return t("account.password.sent", { email: session?.user.email ?? "" }); })}>{t("account.sendCode")}</button>
      ) : (
        <form className="account__form" onSubmit={(e: FormEvent) => { e.preventDefault();
          a.run(async () => { const { error } = await supabase.auth.updateUser({ password, nonce: code }); fail(error);
            setSent(false); setCode(""); setPassword(""); return t("account.password.done"); }); }}>
          <CodeInput id="acc-pw-code" value={code} onChange={setCode} compact />
          <div className="field auth__field">
            <label htmlFor="acc-pw">{t("auth.newPassword")}</label>
            <PasswordInput id="acc-pw" value={password} onChange={setPassword} autoComplete="new-password" />
            <PasswordStrength password={password} />
          </div>
          <div className="actions account__actions">
            <button className="button button--primary" disabled={a.busy || code.length !== 6 || !passwordValid(password)}>{t("account.save")}</button>
            <button type="button" className="button" onClick={() => { setSent(false); setCode(""); }}>{t("account.cancel")}</button>
          </div>
        </form>
      )}
      <Result a={a} />
    </Block>
  );
}

function TwoFactor() {
  const t = useT();
  const [factors, setFactors] = useState<Factor[]>([]);
  const [enrolling, setEnrolling] = useState<{ id: string; qr: string; secret: string } | null>(null);
  const [code, setCode] = useState("");
  const a = useAction();
  const load = useCallback(async () => {
    const { data } = await supabase.auth.mfa.listFactors();
    setFactors((data?.totp ?? []).filter((f) => f.status === "verified"));
  }, []);
  useEffect(() => { load(); }, [load]);
  const active = factors[0];
  return (
    <Block icon={<ShieldCheck size={18} aria-hidden />} title={t("account.mfa.title")} lead={t("account.mfa.lead")}>
      <p className="account__status">
        <span className={`led ${active ? "led--live" : ""}`} aria-hidden /> {active ? t("account.mfa.on") : t("account.mfa.off")}
      </p>
      {active && !enrolling && (
        <button className="button" disabled={a.busy} onClick={() => a.run(async () => {
          const { error } = await supabase.auth.mfa.unenroll({ factorId: active.id }); fail(error); await load(); return t("account.mfa.removed"); })}>
          {t("account.mfa.disable")}
        </button>
      )}
      {!active && !enrolling && (
        <button className="button button--primary" disabled={a.busy} onClick={() => a.run(async () => {
          // Un essai précédent non terminé bloquerait l'inscription : on le retire d'abord.
          const { data: all } = await supabase.auth.mfa.listFactors();
          for (const f of all?.all ?? []) if (f.status !== "verified") await supabase.auth.mfa.unenroll({ factorId: f.id });
          const { data, error } = await supabase.auth.mfa.enroll({ factorType: "totp", friendlyName: "ROMKADE" }); fail(error);
          setEnrolling({ id: data!.id, qr: data!.totp.qr_code, secret: data!.totp.secret }); })}>
          {t("account.mfa.enable")}
        </button>
      )}
      {enrolling && (
        <form className="account__mfa" onSubmit={(e: FormEvent) => { e.preventDefault();
          a.run(async () => { const { error } = await supabase.auth.mfa.challengeAndVerify({ factorId: enrolling.id, code }); fail(error);
            setEnrolling(null); setCode(""); await load(); return t("account.mfa.done"); }); }}>
          <img className="account__qr" src={enrolling.qr} alt="" width={180} height={180} />
          <div>
            <p className="muted">{t("account.mfa.scan")}</p>
            <p className="field__hint">{t("account.mfa.secret")} <code className="account__secret">{enrolling.secret}</code></p>
            <CodeInput id="acc-mfa-code" value={code} onChange={setCode} compact />
            <div className="actions account__actions">
              <button className="button button--primary" disabled={a.busy || code.length !== 6}>{t("account.confirm")}</button>
              <button type="button" className="button" onClick={async () => { await supabase.auth.mfa.unenroll({ factorId: enrolling.id }); setEnrolling(null); setCode(""); }}>
                {t("account.cancel")}
              </button>
            </div>
          </div>
        </form>
      )}
      <Result a={a} />
    </Block>
  );
}

function Consoles() {
  const t = useT();
  const connected = useDeviceStatus().data?.connected === true;
  const [list, setList] = useState<CloudConsole[] | null>(null);
  const [agent, setAgent] = useState<AgentStatus | null>(null);
  const [name, setName] = useState("");
  const a = useAction();
  const qc = useQueryClient();
  const load = useCallback(async () => {
    try { setList(await cloud.consoles()); } catch { setList([]); }
    try { setAgent(await localAgent.status()); } catch { setAgent(null); }
    qc.invalidateQueries({ queryKey: ["cloud-consoles"] });  // voyant de l'onglet
  }, [qc]);
  useEffect(() => { load(); }, [load, connected]);
  const linked = list?.[0];  // une seule console par compte pour l'instant
  const here = connected && agent?.installed === true;  // la console branchée au Manager est celle qui est reliée
  return (
    <Block icon={<Cloud size={18} aria-hidden />} title={t("account.consoles.title")} lead={t("account.consoles.lead")}>
      {list === null ? <span className="auth-spin" aria-hidden /> : linked ? (
        // Console reliée : un seul état, dit en clair, et ce qu'on peut en faire.
        <div className={`account__linked ${linked.online ? "is-online" : ""}`}>
          <div className="account__linked-head">
            <span className={`led ${linked.online ? "led--live" : ""}`} aria-hidden />
            <span className="account__grow">
              <strong>{linked.name}</strong>
              <span className="muted small">{[linked.model, t("account.consoles.games", { count: linked.games })].filter(Boolean).join(" · ")}</span>
            </span>
            <button className="button button--ghost" disabled={a.busy} onClick={() => {
              const next = window.prompt(t("account.consoles.rename"), linked.name)?.trim();
              if (next) a.run(async () => { await cloud.rename(linked.id, next); await load(); });
            }}>{t("account.consoles.rename")}</button>
            <button className="button button--ghost" disabled={a.busy} onClick={() => {
              if (!window.confirm(t("account.consoles.removeConfirm", { name: linked.name }))) return;
              a.run(async () => {
                await cloud.remove(linked.id);
                if (here) await localAgent.unlink().catch(() => undefined);  // l'app ROMKADE s'arrête aussi sur la console
                await load();
              });
            }}>{t("account.consoles.remove")}</button>
          </div>
          <p className="account__linked-state">
            {linked.online ? <><CheckCircle2 size={16} aria-hidden /> {t("account.linked.ready")}</> : t("account.linked.asleep")}
          </p>
          {connected && agent?.supported && !agent.installed && (
            // Console branchée sans l'app ROMKADE (autre console, ou app retirée) : une seule console par compte,
            // la relier remplace celle du compte (son catalogue est renvoyé par l'app au démarrage).
            <div className="account__replace">
              <p className="field__hint">{t("account.link.limit", { name: linked.name })}</p>
              <button className="button button--primary" disabled={a.busy} onClick={() => a.run(async () => {
                await cloud.remove(linked.id); await localAgent.link(); await load(); return t("account.link.done"); })}>
                {a.busy ? <span className="auth-spin" aria-hidden /> : <Cloud size={16} aria-hidden />} {t("account.link.replace")}
              </button>
            </div>
          )}
          {here && agent && (
            <p className="field__hint">
              {t("account.linked.update", { version: agent.version ?? t("account.linked.old") })}{" "}
              {agent.update && <strong className="account__new">{t("account.linked.available", { version: agent.latest })} </strong>}
              <button className="auth__link" disabled={a.busy} onClick={() => a.run(async () => {
                const r = await localAgent.link(); await load();
                return t(r.splash ? "account.linked.updatedLook" : "account.linked.updated"); })}>
                {a.busy ? <span className="auth-spin" aria-hidden /> : null}{t("account.linked.updateGo")}
              </button>
            </p>
          )}
        </div>
      ) : (
        // Aucune console reliée : on relie celle qui est branchée au Manager.
        <div className="account__link">
          <p className="muted">{t("account.consoles.none")} {t("account.link.lead")}</p>
          {!connected ? <p className="field__hint">{t("account.link.offline")}</p>
            : agent && !agent.supported ? <p className="field__hint">{t("account.link.unsupported")}</p> : (
            <form className="field" onSubmit={(e: FormEvent) => { e.preventDefault();
              a.run(async () => { const r = await localAgent.link(name.trim()); await load();
                return t(r.splash ? "account.link.doneLook" : "account.link.done"); }); }}>
              <label htmlFor="acc-console-name">{t("account.link.name")}</label>
              <div className="account__inline">
                <input id="acc-console-name" value={name} maxLength={40} placeholder={t("account.link.namePh")} onChange={(e) => setName(e.target.value)} />
                <button className="button button--primary" disabled={a.busy}>
                  {a.busy ? <span className="auth-spin" aria-hidden /> : <Cloud size={16} aria-hidden />} {t("account.link.go")}
                </button>
              </div>
            </form>
          )}
        </div>
      )}
      <Result a={a} />
      <div className="account__cloud">
        <p className="account__cloud-head"><span className="account__badge">{t("account.cloud.free")}</span> {t("account.cloud.what")}</p>
        <ul>
          <li>{t("account.cloud.ai")}</li>
          <li>{t("account.cloud.anywhere")}</li>
          <li>{t("account.cloud.soon")}</li>
        </ul>
        <p className="field__hint">{t("account.cloud.privacy")}</p>
      </div>
    </Block>
  );
}

function ConnectedApps() {
  const t = useT();
  const [grants, setGrants] = useState<OAuthGrant[] | null>(null);
  const a = useAction();
  const load = useCallback(async () => {
    const { data } = await supabase.auth.oauth.listGrants();
    setGrants(data ?? []);
  }, []);
  useEffect(() => { load(); }, [load]);
  return (
    <Block icon={<AppWindow size={18} aria-hidden />} title={t("account.apps.title")} lead={t("account.apps.lead")}>
      {grants === null ? <span className="auth-spin" aria-hidden /> : grants.length === 0 ? <p className="muted">{t("account.apps.none")}</p> : (
        <ul className="account__list">
          {grants.map((g) => (
            <li key={g.client.id}>
              <span className="account__grow">
                <strong>{g.client.name || g.client.id}</strong>
                <span className="muted small">{t("account.apps.since", { date: date(g.granted_at) })}</span>
              </span>
              <button className="button button--ghost" disabled={a.busy} onClick={() => {
                const name = g.client.name || g.client.id;
                if (!window.confirm(t("account.apps.revokeConfirm", { name }))) return;
                a.run(async () => {
                  const { error } = await supabase.auth.oauth.revokeGrant({ clientId: g.client.id }); fail(error);
                  // Relu après coup : le message ne dit « retiré » que si l'assistant a bien disparu de la liste.
                  const { data } = await supabase.auth.oauth.listGrants();
                  setGrants(data ?? []);
                  if ((data ?? []).some((x) => x.client.id === g.client.id)) throw new Error(t("account.apps.revokeFailed", { name }));
                  return t("account.apps.revoked", { name });
                });
              }}>
                {t("account.apps.revoke")}
              </button>
            </li>
          ))}
        </ul>
      )}
      <Result a={a} />
    </Block>
  );
}

function Sessions() {
  const t = useT();
  const a = useAction();
  return (
    <Block icon={<LogOut size={18} aria-hidden />} title={t("account.sessions.title")} lead={t("account.sessions.lead")}>
      <button className="button" disabled={a.busy} onClick={() => a.run(async () => { const { error } = await supabase.auth.signOut({ scope: "global" }); fail(error); })}>
        {t("account.sessions.everywhere")}
      </button>
      <Result a={a} />
    </Block>
  );
}

function DeleteAccount() {
  const t = useT();
  const { session } = useAuth();
  const [typed, setTyped] = useState("");
  const a = useAction();
  const email = session?.user.email ?? "";
  return (
    <Block title={t("account.danger.title")} lead={t("account.danger.lead")} danger>
      <form className="account__form" onSubmit={(e: FormEvent) => { e.preventDefault();
        a.run(async () => { await cloud.deleteAccount(); await supabase.auth.signOut(); }); }}>
        <div className="field">
          <label htmlFor="acc-delete">{t("account.danger.type")}</label>
          <input id="acc-delete" className="account__narrow" type="email" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={email} autoComplete="off" />
        </div>
        <button className="button button--danger account__danger-go" disabled={a.busy || typed.trim().toLowerCase() !== email.toLowerCase()}>
          {t("account.danger.go")}
        </button>
      </form>
      <Result a={a} />
    </Block>
  );
}
