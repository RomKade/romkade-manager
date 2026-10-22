import type { Factor, OAuthGrant } from "@supabase/supabase-js";
import { AppWindow, Cloud, KeyRound, LogOut, Mail, MonitorSmartphone, ShieldCheck, Trash2, UserRound } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";

import { useDeviceStatus } from "../api/queries";
import { useAuth } from "../auth/AuthContext";
import { CodeInput, PasswordInput } from "../auth/AuthScreen";
import { cloud, localAgent, type CloudConsole } from "../auth/cloud";
import { PasswordStrength, passwordValid } from "../auth/password";
import { supabase } from "../auth/supabase";
import { PageHeader } from "../components/ui";
import { locale, useT } from "../i18n";

/**
 * Mon compte ROMKADE : tout passe par Supabase depuis l'interface (profil, e-mail, mot de passe, double
 * authentification, applications connectées), sauf les consoles reliées et la suppression du compte (ROMKADE Cloud),
 * et la liaison de la console branchée (moteur local du Manager, qui installe l'agent ROMKADE).
 */
export function AccountPage() {
  const t = useT();
  return (
    <div className="page account">
      <PageHeader title={t("account.title")} lead={t("account.lead")} />
      <div className="account__grid">
        <Profile />
        <EmailChange />
        <PasswordChange />
        <TwoFactor />
        <Consoles />
        <ConnectedApps />
        <Sessions />
        <DeleteAccount />
      </div>
    </div>
  );
}

/* ---------- briques ---------- */

function Block({ icon, title, lead, children, danger }: { icon: ReactNode; title: string; lead?: string; children: ReactNode; danger?: boolean }) {
  return (
    <section className={`block account__block ${danger ? "account__block--danger" : ""}`}>
      <div className="block__head"><h2>{icon} {title}</h2></div>
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

const fail = (error: { message?: string } | null) => { if (error) throw new Error(error.message ?? String(error)); };
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
      <form className="account__row" onSubmit={(e: FormEvent) => { e.preventDefault();
        a.run(async () => { const { error } = await supabase.auth.updateUser({ data: { name: name.trim() } }); fail(error); return t("account.saved"); }); }}>
        <div className="field account__grow">
          <label htmlFor="acc-name">{t("account.profile.name")}</label>
          <input id="acc-name" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} required />
        </div>
        <button className="button button--primary" disabled={a.busy || !name.trim()}>{t("account.save")}</button>
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
        <form className="account__row" onSubmit={(e: FormEvent) => { e.preventDefault();
          a.run(async () => { const { error } = await supabase.auth.updateUser({ email: email.trim() }); fail(error); setSent(true); return t("account.email.sent", { email: email.trim() }); }); }}>
          <div className="field account__grow">
            <label htmlFor="acc-email">{t("account.email.new")}</label>
            <input id="acc-email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <button className="button" disabled={a.busy || !email.includes("@")}>{t("account.sendCode")}</button>
        </form>
      ) : (
        <form onSubmit={(e: FormEvent) => { e.preventDefault();
          a.run(async () => { const { error } = await supabase.auth.verifyOtp({ email: email.trim(), token: code, type: "email_change" }); fail(error);
            setSent(false); setCode(""); setEmail(""); return t("account.email.done"); }); }}>
          <CodeInput id="acc-email-code" value={code} onChange={setCode} />
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
        <form onSubmit={(e: FormEvent) => { e.preventDefault();
          a.run(async () => { const { error } = await supabase.auth.updateUser({ password, nonce: code }); fail(error);
            setSent(false); setCode(""); setPassword(""); return t("account.password.done"); }); }}>
          <CodeInput id="acc-pw-code" value={code} onChange={setCode} />
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
            <CodeInput id="acc-mfa-code" value={code} onChange={setCode} />
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
  const [agent, setAgent] = useState<{ supported: boolean; installed: boolean } | null>(null);
  const [name, setName] = useState("");
  const a = useAction();
  const load = useCallback(async () => {
    try { setList(await cloud.consoles()); } catch { setList([]); }
    try { setAgent(await localAgent.status()); } catch { setAgent(null); }
  }, []);
  useEffect(() => { load(); }, [load, connected]);
  return (
    <Block icon={<Cloud size={18} aria-hidden />} title={t("account.consoles.title")} lead={t("account.consoles.lead")}>
      {list === null ? <span className="auth-spin" aria-hidden /> : list.length === 0 ? <p className="muted">{t("account.consoles.none")}</p> : (
        <ul className="account__list">
          {list.map((c) => (
            <li key={c.id}>
              <span className={`led ${c.online ? "led--live" : ""}`} aria-hidden />
              <span className="account__grow">
                <strong>{c.name}</strong>
                <span className="muted small">{[c.model, t("account.consoles.games", { count: c.games }), c.online ? t("account.consoles.online") : t("account.consoles.offline")].filter(Boolean).join(" · ")}</span>
              </span>
              <button className="button button--ghost" onClick={() => {
                const next = window.prompt(t("account.consoles.rename"), c.name)?.trim();
                if (next) a.run(async () => { await cloud.rename(c.id, next); await load(); });
              }}>{t("account.consoles.rename")}</button>
              <button className="button button--ghost" onClick={() => {
                if (window.confirm(t("account.consoles.removeConfirm", { name: c.name }))) a.run(async () => { await cloud.remove(c.id); await load(); });
              }}>{t("account.consoles.remove")}</button>
            </li>
          ))}
        </ul>
      )}
      <div className="account__link">
        <h3><MonitorSmartphone size={16} aria-hidden /> {t("account.link.title")}</h3>
        <p className="muted small">{t("account.link.lead")}</p>
        {!connected ? <p className="field__hint">{t("account.link.offline")}</p>
          : agent && !agent.supported ? <p className="field__hint">{t("account.link.unsupported")}</p> : (
          <form className="account__row" onSubmit={(e: FormEvent) => { e.preventDefault();
            a.run(async () => { await localAgent.link(name.trim()); await load(); return t("account.link.done"); }); }}>
            <div className="field account__grow">
              <label htmlFor="acc-console-name">{t("account.link.name")}</label>
              <input id="acc-console-name" value={name} maxLength={40} placeholder="Ma RG35XX" onChange={(e) => setName(e.target.value)} />
            </div>
            <button className="button button--primary" disabled={a.busy}>
              {a.busy ? <span className="auth-spin" aria-hidden /> : <Cloud size={16} aria-hidden />} {agent?.installed ? t("account.link.again") : t("account.link.go")}
            </button>
          </form>
        )}
        {agent?.installed && connected && (
          <p className="field__hint">{t("account.link.installed")}{" "}
            <button className="auth__link" onClick={() => a.run(async () => { await localAgent.unlink(); await load(); })}>{t("account.link.unlink")}</button>
          </p>
        )}
      </div>
      <Result a={a} />
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
              <button className="button button--ghost" disabled={a.busy} onClick={() => a.run(async () => {
                const { error } = await supabase.auth.oauth.revokeGrant({ clientId: g.client.id }); fail(error); await load(); })}>
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
    <Block icon={<Trash2 size={18} aria-hidden />} title={t("account.danger.title")} lead={t("account.danger.lead")} danger>
      <form onSubmit={(e: FormEvent) => { e.preventDefault();
        a.run(async () => { await cloud.deleteAccount(); await supabase.auth.signOut(); }); }}>
        <div className="field">
          <label htmlFor="acc-delete">{t("account.danger.type")}</label>
          <input id="acc-delete" type="email" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={email} autoComplete="off" />
        </div>
        <button className="button button--danger account__actions" disabled={a.busy || typed.trim().toLowerCase() !== email.toLowerCase()}>
          {t("account.danger.go")}
        </button>
      </form>
      <Result a={a} />
    </Block>
  );
}
