import { Bot, Eye, EyeOff, Gamepad2, LibraryBig, MessagesSquare, Play, Save } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import libraryShot from "../assets/auth/bibliotheque-consoles.webp";
import logo240 from "../assets/brand/romkade-manager-logo-240.webp";
import logo480 from "../assets/brand/romkade-manager-logo-480.webp";
import { LanguageSwitcher } from "../components/TopBar";
import { getLang, useT } from "../i18n";
import { PRIVACY_URL, supabase, TERMS_URL } from "./supabase";

/**
 * Écran de connexion du Manager : à gauche le compte ROMKADE (connexion, inscription avec code par e-mail,
 * mot de passe oublié, double authentification), à droite ce que permet ROMKADE.
 */
type Step = "signin" | "signup" | "verify" | "forgot" | "reset" | "mfa";
const RESEND_SECONDS = 30;

type Props = { needsMfa: boolean; onDone: () => void };

export function AuthScreen({ needsMfa, onDone }: Props) {
  const t = useT();
  const [step, setStep] = useState<Step>(needsMfa ? "mfa" : "signin");
  const [email, setEmail] = useState("");

  return (
    <div className="auth">
      <section className="auth__panel" aria-labelledby="auth-title">
        <header className="auth__top">
          <img className="auth__logo" src={logo240} srcSet={`${logo240} 240w, ${logo480} 480w`} sizes="210px" width={210} height={46}
            alt="ROMKADE Manager" />
          <LanguageSwitcher />
        </header>
        <div className="auth__form" key={step}>
          {step === "signin" && <SignIn email={email} setEmail={setEmail} go={setStep} onDone={onDone} />}
          {step === "signup" && <SignUp email={email} setEmail={setEmail} go={setStep} onDone={onDone} />}
          {step === "verify" && <Verify email={email} go={setStep} onDone={onDone} />}
          {step === "forgot" && <Forgot email={email} setEmail={setEmail} go={setStep} />}
          {step === "reset" && <Reset email={email} go={setStep} onDone={onDone} />}
          {step === "mfa" && <Mfa onDone={onDone} />}
        </div>
        <p className="auth__legal">© 2026 ROMKADE · <a href={TERMS_URL} target="_blank" rel="noreferrer noopener">{t("auth.signup.termsLink")}</a></p>
      </section>
      <Pitch />
    </div>
  );
}

/* ---------- formulaires ---------- */

type StepProps = { go: (s: Step) => void };
type EmailProps = { email: string; setEmail: (v: string) => void };

function errorText(e: { code?: string; message?: string } | null | undefined, t: (k: string) => string): string {
  const code = e?.code ?? "";
  if (["invalid_credentials", "user_already_exists", "weak_password", "otp_expired", "over_email_send_rate_limit"].includes(code)) {
    return t(`auth.err.${code}`);
  }
  if (/invalid login/i.test(e?.message ?? "")) return t("auth.err.invalid_credentials");
  if (/expired|invalid.*(otp|token)/i.test(e?.message ?? "")) return t("auth.err.otp_expired");
  if (/fetch|network/i.test(e?.message ?? "")) return t("auth.offline");
  return e?.message ?? String(e);
}

function useSubmit() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  async function run(work: () => Promise<string | void>) {
    setBusy(true); setError(""); setInfo("");
    try {
      const msg = await work();
      if (msg) setError(msg);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, info, setInfo, setError, run };
}

function Notice({ error, info }: { error: string; info?: string }) {
  if (error) return <p className="auth__notice auth__notice--err" role="alert">{error}</p>;
  if (info) return <p className="auth__notice auth__notice--ok" role="status">{info}</p>;
  return null;
}

function Field({ id, label, children, hint }: { id: string; label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="field auth__field">
      <label htmlFor={id}>{label}</label>
      {children}
      {hint && <p className="field__hint">{hint}</p>}
    </div>
  );
}

function PasswordInput({ id, value, onChange, autoComplete }: { id: string; value: string; onChange: (v: string) => void; autoComplete: string }) {
  const t = useT();
  const [shown, setShown] = useState(false);
  return (
    <div className="auth__password">
      <input id={id} type={shown ? "text" : "password"} value={value} onChange={(e) => onChange(e.target.value)} required
        autoComplete={autoComplete} minLength={autoComplete === "new-password" ? 10 : undefined} />
      <button type="button" className="auth__eye" onClick={() => setShown(!shown)} aria-label={shown ? t("auth.hide") : t("auth.show")}>
        {shown ? <EyeOff size={18} aria-hidden /> : <Eye size={18} aria-hidden />}
      </button>
    </div>
  );
}

function CodeInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const t = useT();
  return (
    <Field id="auth-code" label={t("auth.code")}>
      <input id="auth-code" className="auth__code" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}"
        maxLength={6} value={value} onChange={(e) => onChange(e.target.value.replace(/\D/g, ""))} required autoFocus />
    </Field>
  );
}

function ResendButton({ send }: { send: () => Promise<string | void> }) {
  const t = useT();
  const [left, setLeft] = useState(RESEND_SECONDS);
  const [msg, setMsg] = useState("");
  useEffect(() => {
    if (left <= 0) return;
    const id = setTimeout(() => setLeft(left - 1), 1000);
    return () => clearTimeout(id);
  }, [left]);
  return (
    <>
      <button type="button" className="auth__link" disabled={left > 0}
        onClick={async () => { const err = await send(); setMsg(err || t("auth.resent")); setLeft(RESEND_SECONDS); }}>
        {left > 0 ? t("auth.resendIn", { s: left }) : t("auth.resend")}
      </button>
      {msg && <span className="auth__muted" role="status">{msg}</span>}
    </>
  );
}

function SignIn({ email, setEmail, go, onDone }: EmailProps & StepProps & { onDone: () => void }) {
  const t = useT();
  const [password, setPassword] = useState("");
  const s = useSubmit();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    s.run(async () => {
      const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password });
      if (error?.code === "email_not_confirmed") {
        await supabase.auth.resend({ type: "signup", email: email.trim() });
        return go("verify");
      }
      if (error) return errorText(error, t);
      onDone();
    });
  };
  return (
    <form onSubmit={submit} noValidate={false}>
      <h1 id="auth-title" className="auth__title">{t("auth.signin.title")}</h1>
      <p className="auth__muted">{t("auth.signin.sub")}</p>
      <Field id="auth-email" label={t("auth.email")}>
        <input id="auth-email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
      </Field>
      <Field id="auth-password" label={t("auth.password")}>
        <PasswordInput id="auth-password" value={password} onChange={setPassword} autoComplete="current-password" />
      </Field>
      <Notice error={s.error} />
      <button type="submit" className="button button--primary auth__submit" disabled={s.busy}>
        {s.busy ? <span className="auth-spin" aria-hidden /> : t("auth.signin.submit")}
      </button>
      <div className="auth__links">
        <button type="button" className="auth__link" onClick={() => go("forgot")}>{t("auth.signin.forgot")}</button>
        <span className="auth__muted">{t("auth.signin.noAccount")} <button type="button" className="auth__link" onClick={() => go("signup")}>{t("auth.signin.create")}</button></span>
      </div>
    </form>
  );
}

function SignUp({ email, setEmail, go, onDone }: EmailProps & StepProps & { onDone: () => void }) {
  const t = useT();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [terms, setTerms] = useState(false);
  const s = useSubmit();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!terms) { s.setError(t("auth.err.terms")); return; }
    s.run(async () => {
      const { data, error } = await supabase.auth.signUp({ email: email.trim(), password,
        options: { data: { name: name.trim(), locale: getLang(), terms_accepted_at: new Date().toISOString() } } });
      if (error) return errorText(error, t);
      if (data.user && Array.isArray(data.user.identities) && data.user.identities.length === 0) return t("auth.err.user_already_exists");
      if (data.session) return onDone();
      go("verify");
    });
  };
  const [before, after] = t("auth.signup.terms").split("{terms}");
  const [middle, end] = (after ?? "").split("{privacy}");
  return (
    <form onSubmit={submit}>
      <h1 id="auth-title" className="auth__title">{t("auth.signup.title")}</h1>
      <p className="auth__muted">{t("auth.signup.sub")}</p>
      <Field id="auth-name" label={t("auth.signup.name")}>
        <input id="auth-name" type="text" autoComplete="nickname" maxLength={40} value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
      </Field>
      <Field id="auth-email" label={t("auth.email")}>
        <input id="auth-email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
      </Field>
      <Field id="auth-password" label={t("auth.password")} hint={t("auth.rules")}>
        <PasswordInput id="auth-password" value={password} onChange={setPassword} autoComplete="new-password" />
      </Field>
      <label className="auth__check">
        <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} />
        <span>{before}<a href={TERMS_URL} target="_blank" rel="noreferrer noopener">{t("auth.signup.termsLink")}</a>{middle}
          <a href={PRIVACY_URL} target="_blank" rel="noreferrer noopener">{t("auth.signup.privacyLink")}</a>{end}</span>
      </label>
      <Notice error={s.error} />
      <button type="submit" className="button button--primary auth__submit" disabled={s.busy}>
        {s.busy ? <span className="auth-spin" aria-hidden /> : t("auth.signup.submit")}
      </button>
      <div className="auth__links">
        <span className="auth__muted">{t("auth.signup.have")} <button type="button" className="auth__link" onClick={() => go("signin")}>{t("auth.signin.submit")}</button></span>
      </div>
    </form>
  );
}

function Verify({ email, go, onDone }: { email: string; onDone: () => void } & StepProps) {
  const t = useT();
  const [code, setCode] = useState("");
  const s = useSubmit();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    s.run(async () => {
      const { error } = await supabase.auth.verifyOtp({ email: email.trim(), token: code, type: "signup" });
      if (error) return errorText(error, t);
      onDone();
    });
  };
  return (
    <form onSubmit={submit}>
      <h1 id="auth-title" className="auth__title">{t("auth.verify.title")}</h1>
      <p className="auth__muted">{t("auth.verify.sub", { email })}</p>
      <CodeInput value={code} onChange={setCode} />
      <Notice error={s.error} />
      <button type="submit" className="button button--primary auth__submit" disabled={s.busy || code.length !== 6}>
        {s.busy ? <span className="auth-spin" aria-hidden /> : t("auth.verify.submit")}
      </button>
      <div className="auth__links">
        <ResendButton send={async () => { const { error } = await supabase.auth.resend({ type: "signup", email: email.trim() }); return error ? errorText(error, t) : undefined; }} />
        <button type="button" className="auth__link" onClick={() => go("signin")}>{t("auth.back")}</button>
      </div>
    </form>
  );
}

function Forgot({ email, setEmail, go }: EmailProps & StepProps) {
  const t = useT();
  const s = useSubmit();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    s.run(async () => {
      const { error } = await supabase.auth.resetPasswordForEmail(email.trim());
      if (error) return errorText(error, t);
      go("reset");
    });
  };
  return (
    <form onSubmit={submit}>
      <h1 id="auth-title" className="auth__title">{t("auth.forgot.title")}</h1>
      <p className="auth__muted">{t("auth.forgot.sub")}</p>
      <Field id="auth-email" label={t("auth.email")}>
        <input id="auth-email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
      </Field>
      <Notice error={s.error} />
      <button type="submit" className="button button--primary auth__submit" disabled={s.busy}>
        {s.busy ? <span className="auth-spin" aria-hidden /> : t("auth.forgot.submit")}
      </button>
      <div className="auth__links"><button type="button" className="auth__link" onClick={() => go("signin")}>{t("auth.back")}</button></div>
    </form>
  );
}

function Reset({ email, go, onDone }: { email: string; onDone: () => void } & StepProps) {
  const t = useT();
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const s = useSubmit();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    s.run(async () => {
      const { error } = await supabase.auth.verifyOtp({ email: email.trim(), token: code, type: "recovery" });
      if (error) return errorText(error, t);
      const upd = await supabase.auth.updateUser({ password });
      if (upd.error) return errorText(upd.error, t);
      onDone();
    });
  };
  return (
    <form onSubmit={submit}>
      <h1 id="auth-title" className="auth__title">{t("auth.reset.title")}</h1>
      <p className="auth__muted">{t("auth.verify.sub", { email })}</p>
      <CodeInput value={code} onChange={setCode} />
      <Field id="auth-password" label={t("auth.newPassword")} hint={t("auth.rules")}>
        <PasswordInput id="auth-password" value={password} onChange={setPassword} autoComplete="new-password" />
      </Field>
      <Notice error={s.error} />
      <button type="submit" className="button button--primary auth__submit" disabled={s.busy || code.length !== 6}>
        {s.busy ? <span className="auth-spin" aria-hidden /> : t("auth.reset.submit")}
      </button>
      <div className="auth__links">
        <ResendButton send={async () => { const { error } = await supabase.auth.resetPasswordForEmail(email.trim()); return error ? errorText(error, t) : undefined; }} />
        <button type="button" className="auth__link" onClick={() => go("signin")}>{t("auth.back")}</button>
      </div>
    </form>
  );
}

function Mfa({ onDone }: { onDone: () => void }) {
  const t = useT();
  const [code, setCode] = useState("");
  const s = useSubmit();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    s.run(async () => {
      const { data } = await supabase.auth.mfa.listFactors();
      const factor = (data?.totp ?? []).find((f) => f.status === "verified");
      if (!factor) return onDone();
      const { error } = await supabase.auth.mfa.challengeAndVerify({ factorId: factor.id, code });
      if (error) return t("auth.err.mfa");
      onDone();
    });
  };
  return (
    <form onSubmit={submit}>
      <h1 id="auth-title" className="auth__title">{t("auth.mfa.title")}</h1>
      <p className="auth__muted">{t("auth.mfa.sub")}</p>
      <CodeInput value={code} onChange={setCode} />
      <Notice error={s.error} />
      <button type="submit" className="button button--primary auth__submit" disabled={s.busy || code.length !== 6}>
        {s.busy ? <span className="auth-spin" aria-hidden /> : t("auth.verify.submit")}
      </button>
      <div className="auth__links">
        <button type="button" className="auth__link" onClick={() => supabase.auth.signOut()}>{t("auth.signout")}</button>
      </div>
    </form>
  );
}

/* ---------- présentation ---------- */

const FEATURES = [
  { key: "library", icon: LibraryBig },
  { key: "play", icon: Play },
  { key: "duke", icon: Bot },
  { key: "ai", icon: MessagesSquare },
  { key: "saves", icon: Save },
  { key: "pads", icon: Gamepad2 },
] as const;

/** Fin de titre qui s'écrit, s'efface et change (« enfin rangée. » → « pilotée depuis ChatGPT. »…). */
function RotatingWords({ words }: { words: string[] }) {
  const key = words.join("|");
  const [state, setState] = useState({ index: 0, length: (words[0] ?? "").length, erasing: false });
  const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  useEffect(() => { setState({ index: 0, length: (words[0] ?? "").length, erasing: false }); }, [key]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const word = words[state.index] ?? "";
    const next = (index: number) => ({ index: (index + 1) % words.length, length: 0, erasing: false });
    let delay: number;
    let update: typeof state;
    if (reduced) {
      delay = 3200;
      update = { ...next(state.index), length: (words[(state.index + 1) % words.length] ?? "").length };
    } else if (!state.erasing && state.length < word.length) {
      delay = 55; update = { ...state, length: state.length + 1 };          // écriture
    } else if (!state.erasing) {
      delay = 2600; update = { ...state, erasing: true };                    // pause sur le mot complet
    } else if (state.length > 0) {
      delay = 28; update = { ...state, length: state.length - 1 };           // effacement
    } else {
      delay = 250; update = next(state.index);                               // mot suivant
    }
    const id = setTimeout(() => setState(update), delay);
    return () => clearTimeout(id);
  }, [state, key, reduced]);  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <span className="auth-pitch__rotate" aria-live="off">
      {(words[state.index] ?? "").slice(0, state.length)}<span className="auth-pitch__caret" aria-hidden />
    </span>
  );
}

/** Duke en action : une petite conversation qui se joue en boucle (question, « Duke écrit… », réponse). */
function DukeChat() {
  const t = useT();
  const lines = t("auth.duke.chat").split("|");
  const pairs = Math.floor(lines.length / 2);
  const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const [pair, setPair] = useState(0);
  const [phase, setPhase] = useState<"ask" | "typing" | "answer">(reduced ? "answer" : "ask");
  const [typed, setTyped] = useState(reduced ? (lines[1] ?? "").length : 0);
  const answer = lines[pair * 2 + 1] ?? "";
  useEffect(() => {
    let id: ReturnType<typeof setTimeout>;
    if (reduced) {
      id = setTimeout(() => { setPair((pair + 1) % pairs); setTyped((lines[((pair + 1) % pairs) * 2 + 1] ?? "").length); }, 6000);
    } else if (phase === "ask") {
      id = setTimeout(() => setPhase("typing"), 900);
    } else if (phase === "typing") {
      id = setTimeout(() => { setPhase("answer"); setTyped(0); }, 1400);
    } else if (typed < answer.length) {
      id = setTimeout(() => setTyped(Math.min(answer.length, typed + 2)), 22);
    } else {
      id = setTimeout(() => { setPair((pair + 1) % pairs); setPhase("ask"); setTyped(0); }, 3600);
    }
    return () => clearTimeout(id);
  }, [phase, typed, pair, answer.length, pairs, reduced]);  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <figure className="duke-chat" aria-label={t("auth.duke.title")}>
      <figcaption className="duke-chat__head">
        <span className="duke-chat__avatar"><Bot size={18} aria-hidden /></span>
        <span><strong>{t("auth.duke.title")}</strong><small><span className="duke-chat__dot" aria-hidden />{t("auth.duke.status")}</small></span>
      </figcaption>
      <div className="duke-chat__body" aria-live="off">
        <p className="duke-chat__msg duke-chat__msg--me" key={`q${pair}`}>{lines[pair * 2]}</p>
        {phase === "typing" && (
          <p className="duke-chat__msg duke-chat__msg--duke duke-chat__typing" aria-label={t("auth.duke.typing")}><i /><i /><i /></p>
        )}
        {phase === "answer" && <p className="duke-chat__msg duke-chat__msg--duke">{answer.slice(0, typed)}</p>}
      </div>
    </figure>
  );
}

function Pitch() {
  const t = useT();
  const words = t("auth.pitch.rotate").split("|");
  return (
    <aside className="auth-pitch" aria-label="ROMKADE">
      <div className="auth-pitch__glow" aria-hidden />
      <div className="auth-pitch__inner">
        <p className="auth-pitch__kicker">{t("auth.pitch.kicker")}</p>
        <h2 className="auth-pitch__title">
          <span>{t("auth.pitch.title1")}</span>
          <RotatingWords words={words} />
        </h2>
        <p className="auth-pitch__lead">{t("auth.pitch.lead")}</p>
        <ul className="auth-pitch__brands">
          {t("auth.pitch.brands").split("|").map((brand, i) => (
            <li key={brand} style={{ animationDelay: `${0.35 + i * 0.08}s` }}>{brand}</li>
          ))}
          <li className="auth-pitch__brands-more" style={{ animationDelay: "0.8s" }}>{t("auth.pitch.more")}</li>
        </ul>
        <div className="auth-pitch__shots">
          <img className="auth-pitch__shot auth-pitch__shot--library" src={libraryShot} alt="" aria-hidden width={1156} height={843} />
          <DukeChat />
        </div>
        <ul className="auth-pitch__features">
          {FEATURES.map(({ key, icon: Icon }, i) => (
            <li key={key} style={{ animationDelay: `${0.25 + i * 0.09}s` }}>
              <span className="auth-pitch__icon"><Icon size={20} aria-hidden /></span>
              <span><strong>{t(`auth.f.${key}.t`)}</strong>{t(`auth.f.${key}.d`)}</span>
            </li>
          ))}
        </ul>
        <p className="auth-pitch__free">{t("auth.pitch.free")}</p>
      </div>
    </aside>
  );
}
