import { createClient } from "@supabase/supabase-js";

/**
 * Comptes ROMKADE (Supabase Auth) : le Manager, installé sur l'ordinateur, se connecte directement à Supabase.
 * Adresse du projet et clé publique : faites pour être publiques (la sécurité vient des règles de Supabase).
 * La session est gardée dans le navigateur (localStorage, clé « romkade-auth ») et renouvelée automatiquement.
 */
export const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || "https://urpvxqtyscuomkusqsiu.supabase.co";
const SUPABASE_KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || "sb_publishable_4TKxIKKsIU97CwTtATuckw_mhYMMlPq";

export const supabase = createClient(SUPABASE_URL, SUPABASE_KEY, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false, storageKey: "romkade-auth" },
});

/** Pages légales du site (inscription). */
export const TERMS_URL = "https://romkade.com/conditions-utilisation/";
export const PRIVACY_URL = "https://romkade.com/confidentialite/";
