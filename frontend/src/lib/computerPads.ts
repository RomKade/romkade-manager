import { useEffect, useState, useSyncExternalStore } from "react";

import { api, type Controller, type Players } from "../api/client";
import { controllerName } from "./players";

/**
 * Manettes de l'ordinateur : une manette connectée à l'ordinateur (Bluetooth ou USB) pilote la console par le Wi-Fi.
 * Le navigateur la lit (API Gamepad) et envoie chaque changement par WebSocket ; Game Manager le relaie par SSH à
 * une manette virtuelle de la console (backend app/device/gamepad.py), dont le champ `remote` (GET /api/players)
 * vaut l'identifiant du relais.
 *
 * Les relais vivent tant que l'onglet est ouvert, d'une page à l'autre de l'application (pas liés à un composant).
 */
export type RelayStatus = "connecting" | "live" | "error";
export type ComputerRelay = { token: string; pad: number; name: string; status: RelayStatus; error?: string };

type Live = ComputerRelay & { ws: WebSocket; last: string };

const relays = new Map<string, Live>();
const listeners = new Set<() => void>();
let list: ComputerRelay[] = [];
let frame = 0;

const RELEASE = '{"release": true}';
const round = (v: number) => Math.round(v * 1000) / 1000;

function changed() {
  list = [...relays.values()].map(({ token, pad, name, status, error }) => ({ token, pad, name, status, error }));
  listeners.forEach((l) => l());
}

export const gamepadsSupported = () =>
  typeof navigator !== "undefined" && "getGamepads" in navigator && typeof window !== "undefined" && window.isSecureContext;

/** Nom lisible d'une manette du navigateur (Chrome ajoute « (STANDARD GAMEPAD Vendor: …) »). */
export const padName = (pad: Gamepad) => pad.id.replace(/\s*\(.*\)\s*$/, "").trim() || pad.id;

function snapshot(pad: Gamepad): string {
  return JSON.stringify({ b: pad.buttons.map((b) => round(b.value || (b.pressed ? 1 : 0))), a: pad.axes.map(round) });
}

function loop() {
  const pads = navigator.getGamepads();
  for (const r of relays.values()) {
    if (r.status !== "live" || r.ws.readyState !== WebSocket.OPEN) continue;
    const p = pads[r.pad];
    const snap = p?.connected ? snapshot(p) : RELEASE;  // manette éteinte : rien ne reste appuyé sur la console
    if (snap !== r.last) {
      r.ws.send(snap);
      r.last = snap;
    }
  }
  frame = [...relays.values()].some((r) => r.status === "live") ? requestAnimationFrame(loop) : 0;
}

// Onglet masqué : le navigateur ne lit plus les manettes, on relâche tout.
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) return;
    for (const r of relays.values()) {
      if (r.ws.readyState === WebSocket.OPEN) r.ws.send(RELEASE);
      r.last = RELEASE;
    }
  });
}

/** Relaie la manette `pad` du navigateur vers la console ; rend l'identifiant du relais une fois la manette
 * virtuelle créée sur la console. */
export function startRelay(pad: number, name: string): Promise<string> {
  const token = Math.random().toString(36).slice(2, 10).padEnd(4, "0");
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/gamepad/ws?token=${token}`);
  const r: Live = { token, pad, name, status: "connecting", ws, last: "" };
  relays.set(token, r);
  changed();
  return new Promise((resolve, reject) => {
    const fail = (message: string) => {
      r.status = "error";
      r.error = message;
      relays.delete(token);
      changed();
      reject(new Error(message));
    };
    ws.onmessage = (e) => {
      const msg = JSON.parse(String(e.data));
      if (msg.ready) {
        r.status = "live";
        changed();
        if (!frame) frame = requestAnimationFrame(loop);
        resolve(token);
      } else if (msg.error) {
        fail(msg.error.message);
      }
    };
    ws.onclose = () => {
      if (r.status === "connecting") fail("");
      else if (relays.delete(token)) changed();  // console injoignable, Manager arrêté : la manette a disparu
    };
  });
}

export function stopRelay(token: string) {
  const r = relays.get(token);
  if (!r) return;
  relays.delete(token);
  r.ws.onclose = null;
  r.ws.close();
  changed();
}

/** Relais actifs de cet onglet. */
export function useRelays(): ComputerRelay[] {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => list, () => list);
}

/** Manettes vues par le navigateur (une manette n'apparaît qu'après un appui sur l'un de ses boutons). */
export function useComputerPads(): Gamepad[] {
  const [pads, setPads] = useState<Gamepad[]>([]);
  useEffect(() => {
    if (!gamepadsSupported()) return;
    const read = () => setPads(navigator.getGamepads().filter((g): g is Gamepad => !!g));
    read();
    window.addEventListener("gamepadconnected", read);
    window.addEventListener("gamepaddisconnected", read);
    return () => {
      window.removeEventListener("gamepadconnected", read);
      window.removeEventListener("gamepaddisconnected", read);
    };
  }, []);
  return pads;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Relaie une manette de l'ordinateur et attend que la console la voie : manettes à jour et numéro de la manette
 * virtuelle. En cas d'échec, le relais est arrêté et l'erreur a un message lisible. */
export async function linkComputerPad(pad: Gamepad, t: (key: string) => string): Promise<{ players: Players; index: number }> {
  let token = "";
  try {
    token = await startRelay(pad.index, padName(pad));
    for (let i = 0; i < 12; i++) {
      await sleep(500);
      const d = await api.players();
      const c = d.controllers.find((x) => x.remote === token);
      if (c) return { players: d, index: c.index };
    }
    throw new Error(t("players.computerNotSeen"));
  } catch (e) {
    if (token) stopRelay(token);
    throw new Error((e as Error).message || t("players.computerLost"));
  }
}

/** Arrête les manettes de l'ordinateur qu'aucun joueur n'utilise plus. */
export function dropUnusedRelays(d: Players) {
  for (const r of list) {
    const c = d.controllers.find((x) => x.remote === r.token);
    if (!c || !d.players.includes(c.index)) stopRelay(r.token);
  }
}

/** Nom d'une manette de la console ; la manette virtuelle d'un relais porte le nom de la manette de l'ordinateur. */
export function controllerLabel(c: Controller, relays: ComputerRelay[],
                                t: (key: string, vars?: Record<string, string | number>) => string): string {
  if (!c.remote) return controllerName(c, t);
  const r = relays.find((x) => x.token === c.remote);
  return r ? t("players.computerPad", { name: r.name }) : t("players.computerPadOther");
}
