import { t } from "../i18n/core";
import { supabase } from "./supabase";

/**
 * API du compte ROMKADE : consoles reliées et suppression du compte (ROMKADE Cloud, mcp.romkade.com), liaison de la
 * console branchée au Manager (moteur local, /api/cloud). Toujours avec le jeton de la session en cours.
 */
export const CLOUD_URL = import.meta.env.VITE_ROMKADE_CLOUD_URL || "https://mcp.romkade.com";

export type CloudConsole = {
  id: string; name: string; model: string | null; firmware: string | null; online: boolean; games: number;
  last_seen: number | null;
};

async function token(): Promise<string> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new Error("session");
  return data.session.access_token;
}

async function call<T>(url: string, init: RequestInit = {}, header = "Authorization"): Promise<T> {
  const t = await token();
  const r = await fetch(url, { ...init, headers: { "Content-Type": "application/json", ...(init.headers ?? {}),
    [header]: header === "Authorization" ? `Bearer ${t}` : t } });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(errorMessage(url, r.status, body));
  return body as T;
}

/** Message lisible : un moteur local trop ancien n'a pas les routes /api/cloud (404, 405). */
function errorMessage(url: string, status: number, body: { error?: { message?: string } | string }): string {
  if (url.startsWith("/api/cloud") && (status === 404 || status === 405)) return t("account.link.outdated");
  const err = body?.error;
  return (typeof err === "string" ? err : err?.message) ?? t("account.err.generic", { detail: `HTTP ${status}` });
}

export const cloud = {
  consoles: () => call<{ consoles: CloudConsole[] }>(`${CLOUD_URL}/api/me/consoles`).then((r) => r.consoles),
  rename: (id: string, name: string) => call(`${CLOUD_URL}/api/me/consoles/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),
  remove: (id: string) => call(`${CLOUD_URL}/api/me/consoles/${id}`, { method: "DELETE" }),
  deleteAccount: () => call(`${CLOUD_URL}/api/me`, { method: "DELETE" }),
};

/** Moteur local du Manager : agent ROMKADE de la console branchée. */
export const localAgent = {
  status: async () => {
    const r = await fetch("/api/cloud/agent");
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(errorMessage("/api/cloud/agent", r.status, body));
    return body as { supported: boolean; installed: boolean; server: string | null; cloud: string };
  },
  link: (name?: string) => call<{ console: CloudConsole; reused: boolean }>("/api/cloud/link",
    { method: "POST", body: JSON.stringify({ name: name || null }) }, "X-Romkade-Token"),
  unlink: async () => {
    const r = await fetch("/api/cloud/agent", { method: "DELETE" });
    if (!r.ok) throw new Error(errorMessage("/api/cloud/agent", r.status, await r.json().catch(() => ({}))));
  },
};
