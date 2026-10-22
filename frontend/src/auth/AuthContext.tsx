import type { Session } from "@supabase/supabase-js";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { useT } from "../i18n";
import { onPhone } from "../lib/phone";
import { AuthScreen } from "./AuthScreen";
import { supabase } from "./supabase";

/**
 * Compte ROMKADE obligatoire : le Manager ne s'ouvre qu'une fois connecté (et la double authentification passée
 * si elle est activée). La session est mémorisée : on ne se reconnecte pas à chaque ouverture. Sauf sur un téléphone
 * associé par QR code (lib/phone).
 */
type Status = "loading" | "signedOut" | "needsMfa" | "signedIn";

type AuthValue = { session: Session | null; signOut: () => Promise<void> };
const AuthContext = createContext<AuthValue>({ session: null, signOut: async () => undefined });

/** Compte connecté (null hors de la barrière : tests, pages publiques). */
export function useAuth() {
  return useContext(AuthContext);
}

async function statusOf(session: Session | null): Promise<Status> {
  if (!session) return "signedOut";
  const { data } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
  return data && data.nextLevel === "aal2" && data.currentLevel !== "aal2" ? "needsMfa" : "signedIn";
}

export function AuthGate({ children }: { children: ReactNode }) {
  const t = useT();
  const [session, setSession] = useState<Session | null>(null);
  const [status, setStatus] = useState<Status>("loading");

  const refresh = useCallback(async (s: Session | null) => {
    setSession(s);
    setStatus(await statusOf(s));
  }, []);

  useEffect(() => {
    let alive = true;
    supabase.auth.getSession().then(({ data }) => { if (alive) refresh(data.session); });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => { if (alive) refresh(s); });
    return () => { alive = false; sub.subscription.unsubscribe(); };
  }, [refresh]);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
    setSession(null);
    setStatus("signedOut");
  }, []);

  // Téléphone associé par QR code depuis l'ordinateur connecté : pas d'écran de connexion (sa vérification
  // anti-robot n'est autorisée que sur localhost et romkade.com) ; le compte se gère sur l'ordinateur.
  if (onPhone()) return <>{children}</>;
  if (status === "loading") {
    return <div className="auth-loading" role="status"><span className="auth-spin" aria-hidden />{t("auth.loading")}</div>;
  }
  if (status !== "signedIn") {
    return <AuthScreen needsMfa={status === "needsMfa"} onDone={async () => refresh((await supabase.auth.getSession()).data.session)} />;
  }
  return <AuthContext.Provider value={{ session, signOut }}>{children}</AuthContext.Provider>;
}
