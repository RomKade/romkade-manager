/**
 * Statistiques d'utilisation anonymes (PostHog Cloud EU), seulement si l'utilisateur les accepte : refusées tant
 * qu'il n'a rien répondu. Le choix est gardé dans ce navigateur. Clé absente au build (VITE_POSTHOG_KEY) : la
 * fonction n'existe pas, ni question ni réglage.
 *
 * Rien d'identifiant ne part : textes et attributs des éléments masqués (pas de titres de jeux ni de saisies),
 * adresses réduites au chemin (ni adresse IP de la machine ni recherche), pas de provenance, pas d'enregistrement
 * de session. Version sans dépendance externe : aucun script téléchargé depuis PostHog.
 */
import type { CaptureResult, PostHog } from "posthog-js/dist/module.no-external";

import { APP_VERSION } from "../version";
import { getLang } from "../i18n";

const KEY = import.meta.env.VITE_POSTHOG_KEY?.trim();
const HOST = import.meta.env.VITE_POSTHOG_HOST?.trim() || "https://eu.i.posthog.com";
const STORAGE_KEY = "romkade-analytics";

export type Consent = "on" | "off" | null;

/** La clé PostHog a été fournie au build : la question et le réglage s'affichent. */
export const analyticsAvailable = Boolean(KEY);

export function getConsent(): Consent {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "on" || v === "off" ? v : null;
  } catch {
    return null;
  }
}

const listeners = new Set<() => void>();
export function subscribeConsent(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

let client: Promise<PostHog> | null = null;

function start(): void {
  if (!KEY || client) return;
  client = import("posthog-js/dist/module.no-external").then(({ default: posthog }) => {
    posthog.init(KEY, {
      api_host: HOST,
      persistence: "localStorage",
      person_profiles: "identified_only",
      capture_pageview: "history_change",
      capture_pageleave: true,
      autocapture: true,
      mask_all_text: true,
      mask_all_element_attributes: true,
      save_referrer: false,
      save_campaign_params: false,
      disable_session_recording: true,
      disable_surveys: true,
      disable_external_dependency_loading: true,
      advanced_disable_flags: true,
      before_send: sanitize,
    });
    posthog.register({ app_version: APP_VERSION, app_lang: getLang() });
    return posthog;
  });
  client.catch(() => { client = null; });
}

export function setConsent(value: "on" | "off"): void {
  try { localStorage.setItem(STORAGE_KEY, value); } catch { /* navigation privée : la question reviendra */ }
  if (value === "on") {
    start();
    client?.then((ph) => ph.opt_in_capturing()).catch(() => undefined);
  } else {
    client?.then((ph) => { ph.opt_out_capturing(); ph.reset(); }).catch(() => undefined);
  }
  listeners.forEach((fn) => fn());
}

/** Au chargement de l'application : démarre seulement si l'utilisateur a déjà accepté. */
export function initAnalytics(): void {
  if (getConsent() === "on") start();
}

const URL_PROPS = ["$current_url", "$referrer", "$prev_pageview_url", "$initial_current_url", "$initial_referrer"];
const DROP_PROPS = ["$host", "$referring_domain", "$initial_referring_domain", "$initial_host", "$search_engine"];

/** Adresse réduite à son chemin : ni hôte (adresse IP du serveur, domaine ngrok) ni paramètres (recherches). */
function pathOnly(value: unknown): unknown {
  if (typeof value !== "string" || !value) return value;
  try {
    return new URL(value, "http://x").pathname;
  } catch {
    return null;
  }
}

export function sanitize(event: CaptureResult | null): CaptureResult | null {
  if (!event) return event;
  for (const bag of [event.properties, event.$set, event.$set_once]) {
    if (!bag) continue;
    for (const k of URL_PROPS) if (k in bag) bag[k] = pathOnly(bag[k]);
    for (const k of DROP_PROPS) delete bag[k];
  }
  return event;
}
