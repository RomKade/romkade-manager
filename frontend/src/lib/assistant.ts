/**
 * Assistant de jeu, côté interface : état partagé par la bulle de la page et celle de la fiche d'un jeu (la fiche est
 * une fenêtre modale : la bulle y est rendue à nouveau, avec la même conversation), et lecture de la réponse en flux.
 */
import { useSyncExternalStore } from "react";

export type AssistantGame = { id: number; title: string; platform: string };
export type Scope = { kind: "library" } | { kind: "game"; game: AssistantGame };
export type ChatSource = { source: string; page: string; url: string; license: string };
export type ChatMessage =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string; intent?: string | null; games?: AssistantGame[]; sources?: ChatSource[];
      pending?: boolean }
  | { role: "refusal"; reason: string }
  | { role: "error"; message: string };

type State = {
  open: boolean;
  /** Bulle masquée (Paramètres > Assistant IA), mémorisé dans ce navigateur. */
  hidden: boolean;
  scope: Scope;
  /** Jeu détecté : fiche ouverte (prioritaire) ou jeu en cours sur la console. */
  sheetGame: AssistantGame | null;
  sheetOpen: boolean;
  /** Jeu dont la proposition « Discuter de ce jeu ? » a été fermée (elle revient pour un autre jeu). */
  dismissedOffer: number | null;
  conversations: Record<string, ChatMessage[]>;
};

const STORAGE = "romkade-assistant";
const HIDDEN = "romkade-assistant-hidden";
const loadHidden = () => { try { return localStorage.getItem(HIDDEN) === "1"; } catch { return false; } };
let state: State = { open: false, hidden: loadHidden(), scope: { kind: "library" }, sheetGame: null, sheetOpen: false,
  dismissedOffer: null, conversations: load() };
const listeners = new Set<() => void>();

function load(): Record<string, ChatMessage[]> {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE) ?? "{}");
  } catch {
    return {};
  }
}

function set(patch: Partial<State>) {
  state = { ...state, ...patch };
  if (patch.conversations) {
    try {
      sessionStorage.setItem(STORAGE, JSON.stringify(state.conversations));
    } catch { /* stockage indisponible : la conversation reste en mémoire */ }
  }
  listeners.forEach((l) => l());
}

export const scopeKey = (scope: Scope) => (scope.kind === "game" ? `game:${scope.game.id}` : "library");

export const assistant = {
  get: () => state,
  subscribe: (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; },
  setOpen: (open: boolean) => set({ open }),
  setHidden: (hidden: boolean) => {
    try { if (hidden) localStorage.setItem(HIDDEN, "1"); else localStorage.removeItem(HIDDEN); } catch { /* stockage indisponible */ }
    set({ hidden, open: hidden ? false : state.open });
  },
  setScope: (scope: Scope) => set({ scope }),
  dismissOffer: (gameId: number) => set({ dismissedOffer: gameId }),
  /** La fiche d'un jeu s'ouvre (ou se ferme : null). */
  setSheet: (game: AssistantGame | null) => set({ sheetGame: game, sheetOpen: game != null }),
  messages: (scope: Scope) => state.conversations[scopeKey(scope)] ?? [],
  setMessages: (scope: Scope, messages: ChatMessage[]) =>
    set({ conversations: { ...state.conversations, [scopeKey(scope)]: messages } }),
  /** Tests : état de départ. */
  reset: () => set({ open: false, hidden: false, scope: { kind: "library" }, sheetGame: null, sheetOpen: false,
    dismissedOffer: null, conversations: {} }),
};

export function useAssistant() {
  return useSyncExternalStore(assistant.subscribe, assistant.get);
}

export type StreamEvent =
  | { type: "meta"; in_scope: boolean; reason: string | null; intent: string | null; games: AssistantGame[];
      sources: ChatSource[]; provider: string; local: boolean }
  | { type: "delta"; text: string }
  | { type: "done" }
  | { type: "error"; code: string; message: string };

/** POST /api/assistant, puis lecture des événements SSE au fil de l'eau. Erreur de réglage : ApiError-like. */
export async function askAssistant(
  body: { scope: "library" | "game"; game_id?: number; lang: string; messages: { role: string; content: string }[] },
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/assistant", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
  });
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => null);
    throw Object.assign(new Error(data?.error?.message ?? `Erreur ${res.status}`), { code: data?.error?.code ?? "http_error" });
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const event = /^event: (.+)$/m.exec(block)?.[1];
      const data = /^data: (.+)$/m.exec(block)?.[1];
      if (event && data) onEvent({ type: event, ...JSON.parse(data) } as StreamEvent);
    }
    if (done) break;
  }
}
