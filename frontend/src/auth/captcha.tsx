import { useEffect, useRef, useState } from "react";

import { getLang } from "../i18n";

/**
 * Vérification anti-robot Cloudflare Turnstile, exigée par Supabase Auth pour la connexion, l'inscription, le mot de
 * passe oublié et le renvoi d'un code.
 *
 * La clé de site est publique et la même pour tous : le widget est autorisé sur localhost / 127.0.0.1 (le Manager
 * tourne chez chaque utilisateur) et sur romkade.com. La clé secrète n'est connue que de Supabase, qui vérifie le
 * jeton auprès de Cloudflare. Un jeton ne sert qu'une fois : `reset()` après chaque appel à Supabase.
 */
export const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || "0x4AAAAAAFgdH46TUjayOnli";
const SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

type Turnstile = {
  render: (el: HTMLElement, opts: Record<string, unknown>) => string;
  reset: (id: string) => void;
  remove: (id: string) => void;
};
declare global {
  interface Window { turnstile?: Turnstile }
}

let loading: Promise<void> | null = null;
function loadScript(): Promise<void> {
  if (window.turnstile) return Promise.resolve();
  loading ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = SCRIPT;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => { loading = null; reject(new Error("turnstile")); };
    document.head.appendChild(s);
  });
  return loading;
}

export function useCaptcha() {
  const box = useRef<HTMLDivElement>(null);
  const widget = useRef<string | null>(null);
  const [token, setToken] = useState("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    loadScript().then(() => {
      if (!alive || !box.current || !window.turnstile) return;
      widget.current = window.turnstile.render(box.current, {
        sitekey: TURNSTILE_SITE_KEY, theme: "auto", size: "flexible", language: getLang(),
        callback: (t: string) => { setToken(t); setFailed(false); },
        "expired-callback": () => setToken(""),
        "error-callback": () => { setToken(""); setFailed(true); },
      });
    }).catch(() => { if (alive) setFailed(true); });
    return () => {
      alive = false;
      if (widget.current && window.turnstile) window.turnstile.remove(widget.current);
      widget.current = null;
    };
  }, []);
  const reset = () => {
    setToken("");
    if (widget.current && window.turnstile) window.turnstile.reset(widget.current);
  };
  return { box, token, failed, reset };
}

export type Captcha = ReturnType<typeof useCaptcha>;

/** Emplacement du widget (souvent invisible : Cloudflare ne montre une case à cocher qu'en cas de doute). */
export function CaptchaBox({ captcha, offline }: { captcha: Captcha; offline: string }) {
  return (
    <div className="auth__captcha">
      <div ref={captcha.box} />
      {captcha.failed && <p className="field__hint">{offline}</p>}
    </div>
  );
}
