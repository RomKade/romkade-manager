import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes, makeQueryClient } from "../App";
import { assistant } from "../lib/assistant";

// jsdom ne fait pas de mise en page : la virtualisation est remplacée par un rendu de toutes les lignes.
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count, estimateSize }: { count: number; estimateSize: () => number }) => {
    const size = estimateSize();
    const items = Array.from({ length: count }, (_, i) => ({ index: i, key: i, start: i * size, end: (i + 1) * size, size }));
    return { getVirtualItems: () => items, getTotalSize: () => count * size, measure: () => undefined };
  },
}));

const platform = { id: 1, directory: "SFC", code: "SFC", label: "Super Nintendo" };
const game = (id: number, title: string) => ({
  id, platform, title, normalized_title: title.toLowerCase(), filename: `${title} (USA).smc`,
  relative_path: `${title} (USA).smc`, extension: "smc", region: "USA", size: 524288,
  modified_at: "2026-01-01T00:00:00Z", role: "candidate", has_image: false, image_url: null,
  metadata_status: "not_fetched", genre: "plateforme", genre_label: "Plateforme", genre_detail: "Platform", first_seen_at: "2026-10-16T10:00:00Z", last_seen_at: "2026-10-16T10:00:00Z", present: true,
  youtube_url: `https://www.youtube.com/results?search_query=${title.replaceAll(" ", "+")}+SNES+gameplay`,
});
const status = {
  synced: true, sync_running: false, last_run: null, last_successful_sync_at: "2026-10-16T10:00:00Z",
  platform_count: 1, game_count: 2, file_count: 2, total_bytes: 1048576,
  storage_total_bytes: 47e9, storage_free_bytes: 15e9, storage_measured_at: null,
};

let calls: string[] = [];
let bodies: Record<string, unknown>[] = [];
let deviceOnline = true;
let playingId: number | null = null;
let favoriteIds: number[] = [];
let brokenIds: number[] = [];
let hostKeyTrusted = true;
let relayToken = "";
let assistantBodies: Record<string, unknown>[] = [];
let assistantAction: Record<string, unknown> | null = null;
let controlsSourced = false;
let sheetImages: { boxart_url?: string | null; image_url?: string | null } = {};
let knowledgeJob = { running: false, total: 0, done: 0, found: 0, current: null as string | null, stopping: false };
let savedDescription: unknown = null;
let cheatsReady = false;
let installedCheat: string | null = null;
const cheatsStatus = () => ({ available: cheatsReady, files: cheatsReady ? 27280 : 0, updated_at: cheatsReady ? "2026-10-19T09:00:00Z" : null,
  size: 0, license: "CC BY-SA 4.0", source_url: "https://github.com/libretro/libretro-database/tree/master/cht" });
type FakeLlm = { provider: string | null; model: string | null; base_url: string | null; key: boolean; tested: boolean };
const NO_LLM: FakeLlm = { provider: null, model: null, base_url: null, key: false, tested: false };
let llm: FakeLlm = { ...NO_LLM };
function llmStatus() {
  const local = llm.provider === "local";
  const model = llm.model ?? (llm.provider === "anthropic" ? "claude-opus-5-5" : null);
  const problem = !llm.provider ? "llm_none" : !local && !llm.key ? "llm_key_missing" : !model ? "llm_no_model" : null;
  const state = !llm.provider ? "none" : problem ? "incomplete" : llm.tested ? "connected" : "untested";
  const p = (id: string, kind: string, key: string, base_url: string, default_model: string | null) =>
    ({ id, label: id, kind, key, keys_url: null, base_url, default_model, batch: id === "anthropic",
       key_source: id === llm.provider && llm.key ? "keychain" : null });
  return { provider: llm.provider, model, base_url: llm.base_url, ready: !problem, problem, state, last_error: null,
    tested_at: llm.tested ? "2026-10-18T10:00:00Z" : null, local,
    local_presets: { Ollama: "http://localhost:11434/v1", "LM Studio": "http://localhost:1234/v1", "Ollama (Docker)": "http://host.docker.internal:11434/v1" },
    providers: [p("anthropic", "cloud", "required", "https://api.anthropic.com/v1", "claude-opus-5-5"),
      p("openai", "cloud", "required", "https://api.openai.com/v1", null), p("local", "local", "optional", "http://localhost:11434/v1", null)] };
}
let systemCaps: Record<string, boolean> | null = null; // null : système inconnu (tout reste affiché)
let volume = { percent: 60, muted: false };
// Captures d'écran gardées sur le Mac (deux pour Super Mario World), supprimées par DELETE.
const shot = (name: string) => ({ name, taken_at: "2026-10-19T20:30:00Z", size: 1000, url: `/api/screenshots/1/${name}` });
let shots = [shot("20261019-203001.png"), shot("20261019-203000.png")];
let playAlerts: { id: number; created_at: string; minutes: number; scope: string; game_title: string }[] = [];

function mockFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(url);
    if (init?.body) bodies.push({ url, ...JSON.parse(String(init.body)) });
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    if (url.startsWith("/api/catalog/status")) return json(status);
    if (url.startsWith("/api/device/system")) {
      if (!systemCaps) return json({ error: { code: "device_unreachable", message: "injoignable", details: {} } }, 502);
      const profile = { id: "muos", label: "muOS", status: "experimental", roms_roots: ["/mnt/mmc/ROMS"], launcher: null, quit: "ra-udp",
        save_sources: [], states_in_rom_folder: false, bluetooth: null, notes: "", makers: [], capabilities: systemCaps };
      return json({ chosen: "muos", profile, capabilities: systemCaps, detected: null });
    }
    if (url.startsWith("/api/device/status"))
      return json(deviceOnline ? { connected: true, error: null } : { connected: false, error: { code: "device_unreachable", message: "Console injoignable sur 192.168.86.242:22" } });
    if (url === "/api/device/host-key/trust") { hostKeyTrusted = true; return json({ host: "192.168.86.243", algorithm: "ssh-ed25519", fingerprint: "SHA256:abc", trusted: true }); }
    if (url === "/api/device/host-key") return json({ host: "192.168.86.243", algorithm: "ssh-ed25519", fingerprint: "SHA256:abc", trusted: false });
    if (url.startsWith("/api/settings/llm/models")) return json(["llama3.2:3b", "qwen2.5:7b"]);
    if (url === "/api/settings/llm/test") { llm.tested = true; return json({ ok: true, provider: llm.provider, model: "x", seconds: 2.4 }); }
    if (url.startsWith("/api/settings/llm/key")) { llm = { ...llm, key: init?.method === "PUT", tested: false }; return json(llmStatus()); }
    if (url === "/api/settings/llm") {
      if (init?.body) llm = { ...llm, model: null, base_url: null, ...(JSON.parse(String(init.body)) as object), tested: false };
      return json(llmStatus());
    }    if (url.startsWith("/api/settings")) return json({ host: "192.168.86.242", port: 22, username: "root", auth_method: "password", key_path: null, roms_root: "/mnt/mmc/Roms", connect_timeout: 8, has_password: true, host_key_trusted: hostKeyTrusted });
    if (url.startsWith("/api/platforms")) return json([{ ...platform, label_status: "confirmed", kind: "emulated", present: true, image_dir_present: true, last_scanned_at: null, game_count: 2, file_count: 2, total_bytes: 1048576, image_count: 0, images_matched: 0 }]);
    if (url.startsWith("/api/catalog/facets")) return json({
      extensions: [{ value: "smc", count: 2 }], regions: [{ value: "USA", count: 2 }],
      genres: [{ value: "plateforme", label: "Plateforme", count: 1 }, { value: "sport", label: "Sport", count: 1 }],
      subgenres: [{ value: "sport.golf", label: "Golf", count: 4 }, { value: "sport.tennis", label: "Tennis", count: 3 }],
    });
    if (url.startsWith("/api/uploads")) return json([
      { id: "a".repeat(32), filename: "Zelda (Europe).sfc", size: 2048, sha256: "0", received_at: "" },
      { id: "b".repeat(32), filename: "Super Mario World (USA).smc", size: 999, sha256: "0", received_at: "" },
    ]);
    if (url.startsWith("/api/transfers/plan")) return json({
      items: [
        { upload_id: "a".repeat(32), filename: "Zelda (Europe).sfc", size: 2048, platform: "SFC", platform_label: "Super Nintendo", platform_choices: ["SFC"], conflict: null, warnings: [], error: null },
        { upload_id: "b".repeat(32), filename: "Super Mario World (USA).smc", size: 999, platform: "SFC", platform_label: "Super Nintendo", platform_choices: ["SFC"], conflict: { existing: "Super Mario World (USA).smc", existing_size: 512, same_size: false }, warnings: [], error: null },
      ],
      total_bytes: 3047, free_bytes: 15e9, margin_bytes: 268435456, fits: true, ready: true,
    });
    if (url.startsWith("/api/transfers")) return url.includes("plan") ? json({}) : (init?.method === "POST" ? json([], 202) : json([]));
    const playSettings = { alert_enabled: true, alert_minutes: 240, alert_scope: "day", repeat_minutes: 30, console_message: true };
    if (url.startsWith("/api/play/alerts/")) { playAlerts = []; return new Response(null, { status: 204 }); }
    if (url.startsWith("/api/search")) return json({ items: [game(1, "Super Mario World")], total: 1, engine: "typesense" });
    if (url.startsWith("/api/play/recent")) return json([
      { title: "Super Mario World", platform: "SFC", rom_path: "/mnt/mmc/Roms/SFC/Super Mario World (USA).smc",
        game: game(1, "Super Mario World"), last_played: "2026-10-16T10:00:00Z", seconds: 3900 },
    ]);
    if (/^\/api\/games\/\d+\/launch/.test(url)) return json({ status: "launching", rom_path: "x", slot: null }, 202);
    if (url.startsWith("/api/play/state")) return json({ playing: false, game: null, title: null, session_started_at: null,
      session_seconds: 0, today_seconds: 3 * 3600, settings: playSettings, alerts: playAlerts });
    if (url.startsWith("/api/play/settings")) return json(playSettings);
    if (url.startsWith("/api/play/reset")) return new Response(null, { status: 204 });
    if (url.startsWith("/api/play/stats")) return json({
      today_seconds: 3 * 3600, week_seconds: 9 * 3600, total_seconds: 20 * 3600, retroarch_available: true,
      days: Array.from({ length: 14 }, (_, i) => ({ date: `2026-10-${String(3 + i).padStart(2, "0")}`, seconds: i * 600 })),
      games: [{ key: "id:1", ra_seconds: 3600, title: "Super Mario World", platform: "SFC", game: game(1, "Super Mario World"), seconds: 7200, sessions: 3,
        last_played: "2026-10-16T10:00:00Z", last_played_console: null }],
      sessions: [{ id: 1, title: "Super Mario World", platform: "SFC", game: game(1, "Super Mario World"),
        started_at: "2026-10-16T08:00:00Z", ended_at: "2026-10-16T10:00:00Z", seconds: 7200 }],
    });
    if (url === "/api/device/screenshot") {
      shots = [shot("20261019-210000.png"), ...shots];
      return json({ game_id: 1, title: "Super Mario World", shot: shots[0] });
    }
    if (url.startsWith("/api/screenshots/") && init?.method !== "DELETE")
      return new Response(new Uint8Array([137, 80, 78, 71]), { headers: { "Content-Type": "image/png" } });
    if (url.startsWith("/api/screenshots/") && init?.method === "DELETE") {
      shots = shots.filter((s) => s.url !== url);
      return new Response(null, { status: 204 });
    }
    if (url === "/api/screenshots") return json(shots.length ? [{ game_id: 1, title: "Super Mario World", platform_code: "SFC", platform_label: "Super Nintendo", shots }] : []);
    if (url === "/api/games/1/screenshots") return json(shots);
    if (url.startsWith("/api/device/now-playing")) return json(playingId
      ? { playing: true, process: "retroarch", rom_path: "/mnt/mmc/Roms/SFC/Super Mario World (USA).smc", menu: false, game: game(playingId, "Super Mario World") }
      : { playing: false, process: null, rom_path: null, menu: true, game: null });
    const dev = (address: string, name: string, kind: string, paired: boolean, connected: boolean, rssi: number | null) =>
      ({ address, name, icon: "", kind, paired, trusted: paired, connected, rssi });
    if (url === "/api/bluetooth/test-sound") return json({ result: "played" });
    if (url.startsWith("/api/bluetooth")) return json({
      adapter: { present: true, powered: true, discovering: false, name: "ANBERNIC" }, bluealsa: true, audio_output: null,
      devices: [dev("AA:00:00:00:00:01", "Voisin 1", "other", false, false, -40), dev("70:77:81:54:FF:14", "KD-43X8309C", "audio", false, false, -70),
        dev("F8:DF:15:00:00:02", "JBL Flip", "audio", true, true, -50)],
    });
    if (url === "/api/device/clock") return json({ console_epoch: 1662019043, timezone: "Etc/UTC", utc_offset: "+0000", mac_epoch: 1792188582, drift_seconds: -130169539 });
    if (url === "/api/device/clock/sync") return json({ console_epoch: 1792188582, timezone: "Europe/Paris", utc_offset: "+0200", mac_epoch: 1792188582, drift_seconds: 0 });
    if (url === "/api/device/diagnose") return json({ ok: false, host: "192.168.86.242", port: 22, steps: [
      { id: "network", status: "failed", ms: 12, detail: null, code: "local_network_blocked", message: "macOS bloque l'accès au réseau local" },
      ...["ssh", "host_key", "auth", "command", "roms"].map((id) => ({ id, status: "skipped", ms: null, detail: null, code: null, message: null })),
    ] });
    if (url.startsWith("/api/volume")) {
      const body = init?.method === "PUT" ? JSON.parse(String(init.body)) as { percent?: number; muted?: boolean } : {};
      volume = { ...volume, ...(body.percent != null ? { percent: body.percent, muted: false } : {}), ...(body.muted != null ? { muted: body.muted } : {}) };
      return json({ mode: "game_manager", adjustable: true, game_running: true, ...volume });
    }
    if (url.startsWith("/api/players")) {
      const body = init?.method === "PUT" ? JSON.parse(String(init.body)) as { players?: number[]; directions?: number[] } : {};
      // Manette de l'ordinateur relayée (WebSocket simulé) : manette virtuelle n°4 de la console.
      const relayed = relayToken ? [{ index: 4, name: "Microsoft X-Box 360 pad", builtin: false, remote: relayToken }] : [];
      return json({ controllers: [{ index: 0, name: "ANBERNIC-keys", builtin: true }, { index: 1, name: "8BitDo Pro 2", builtin: false }, ...relayed],
        players: body.players ?? [2, 1, 0, 3], directions: body.directions ?? [2, null, null, null],
        applied: !(playingId && init?.method === "PUT"), game_running: playingId != null });
    }
    if (url.startsWith("/api/saves/howto")) return json([{ action: "save_state", combo: ["Menu", "R1"] }, { action: "quit", combo: ["Menu", "Start"] }]);
    if (url.startsWith("/api/saves/backups")) return json([]);
    if (url === "/api/saves/delete") return json({ deleted: "x", copy: "20261016-100000-auto" });
    if (url.startsWith("/api/saves")) return json({ scanned_at: "2026-10-16T10:00:00Z", saves: [
      { path: "/mnt/mmc/states_RA/Roms/SFC/Snes9x/Super Mario World (USA).state1", rel: "states_RA/Roms/SFC/Snes9x/Super Mario World (USA).state1",
        source: "retroarch", kind: "state", slot: "1", platform: "SFC", name: "Super Mario World (USA)", size: 4096,
        modified_at: "2026-10-16T10:00:00Z", game: game(1, "Super Mario World") },
    ] });
    if (/^\/api\/games\/\d+\/saves/.test(url)) return json([
      { path: "/mnt/mmc/saves_RA/Roms/SFC/Snes9x/Super Mario World (USA).srm", rel: "saves_RA/Roms/SFC/Snes9x/Super Mario World (USA).srm",
        source: "retroarch", kind: "sram", slot: null, platform: "SFC", name: "Super Mario World (USA)", size: 2048,
        modified_at: "2026-10-16T10:00:00Z", game: null },
    ]);
    if (url === "/api/assistant") {
      assistantBodies.push(JSON.parse(String(init?.body)));
      if (assistantAction) {
        return new Response([
          `event: meta\ndata: ${JSON.stringify({ in_scope: true, reason: null, intent: "console_action", games: [], sources: [], provider: "local", local: true })}\n\n`,
          `event: action\ndata: ${JSON.stringify(assistantAction)}\n\n`, "event: done\ndata: {}\n\n",
        ].join(""), { status: 200, headers: { "Content-Type": "text/event-stream" } });
      }
      const sse = [
        `event: meta\ndata: ${JSON.stringify({ in_scope: true, reason: null, intent: "game_help", games: [], provider: "local", local: true,
          sources: [{ source: "strategywiki", page: "Super Mario World/Vanilla Dome", url: "https://strategywiki.org/wiki/Super_Mario_World/Vanilla_Dome", license: "CC BY-SA 4.0" }] })}\n\n`,
        `event: delta\ndata: ${JSON.stringify({ text: "Indice : utilise " })}\n\n`,
        `event: delta\ndata: ${JSON.stringify({ text: "la cape." })}\n\n`,
        "event: done\ndata: {}\n\n",
      ].join("");
      return new Response(sse, { status: 200, headers: { "Content-Type": "text/event-stream" } });
    }
    if (url === "/api/cheats/download") { cheatsReady = true; return json(cheatsStatus()); }
    if (url === "/api/cheats") return json(cheatsStatus());
    if (/^\/api\/games\/\d+\/cheats\/install/.test(url)) {
      installedCheat = (JSON.parse(String(init!.body)) as { name: string }).name;
      return json({ path: "/.config/retroarch/cheats/x/Super Mario World (USA).cht" });
    }
    if (/^\/api\/games\/\d+\/cheats/.test(url)) return json({ available: cheatsReady, can_install: true, license: "CC BY-SA 4.0",
      source_url: "https://github.com/libretro/libretro-database/tree/master/cht", files: cheatsReady ? [
        { name: "SNES/Super Mario World (USA).cht", label: "USA", system: "SNES", count: 10,
          cheats: Array.from({ length: 10 }, (_, i) => ({ desc: i === 0 ? "Vies infinies" : `Code ${i}`, code: `7E0DBE:${i}` })) },
        { name: "SNES/Super Mario World (USA) (Game Genie).cht", label: "USA · Game Genie", system: "SNES", count: 1,
          cheats: [{ desc: "Start with 9 lives", code: "DD6A-1F0D" }] }] : [] });
    if (/^\/api\/games\/\d+\/description/.test(url)) {
      if (init?.method === "PUT") { savedDescription = JSON.parse(String(init.body)); return json({ texts: 2 }); }
      return json({ mode: "translate", model: "qwen", known: true, texts: {
        en: { text: "Mario's quest to save the princess.", origin: "source" },
        fr: { text: "Mario doit délivrer la princesse Peach.", origin: "translated" } } });
    }
    if (url.startsWith("/api/knowledge")) {
      if (url === "/api/knowledge/start") knowledgeJob = { running: true, total: 1, done: 0, found: 0, current: "zelda", stopping: false };
      return json({ games: 2, found: 1, not_found: 0, errors: 0, pending: knowledgeJob.running ? 1 : 1, chunks: 30,
        auto_after_sync: false, job: knowledgeJob, license: "CC BY-SA 4.0" });
    }
    if (/^\/api\/games\/\d+\/knowledge\/search/.test(url)) return json([{ source: "strategywiki", lang: "en",
      page: "Super Mario World/Vanilla Dome", section: "Walkthrough", url: "https://strategywiki.org/wiki/Super_Mario_World/Vanilla_Dome",
      license: "CC BY-SA 4.0", excerpt: "Use the cape to fly over the castle wall" }]);
    if (/^\/api\/games\/\d+\/knowledge/.test(url)) return json(init?.method === "POST"
      ? { status: "found", fetched_at: "2026-10-18T10:00:00Z", error: null, chunks: 30, sections: ["Gameplay"],
          sources: [{ source: "wikipedia", lang: "en", page: "Super Mario World", url: "https://en.wikipedia.org/wiki/Super_Mario_World", chunks: 13, license: "CC BY-SA 4.0" }] }
      : { status: "none", fetched_at: null, error: null, chunks: 0, sections: [], sources: [] });
    if (/^\/api\/games\/\d+\/favorite/.test(url)) {
      const id = Number(url.split("/")[3]);
      favoriteIds = init?.method === "PUT" ? [id, ...favoriteIds.filter((f) => f !== id)] : favoriteIds.filter((f) => f !== id);
      return new Response(null, { status: 204 });
    }
    if (/^\/api\/games\/\d+\/screenshots\/[^/]+\/caption/.test(url)) {
      const n = bodies.filter((b) => String(b.url).endsWith("/caption")).length;
      return json({ text: `Brouillon ${n} de l'IA\n#retrogaming`, model: "Gemma", saw_image: true });
    }
    if (/^\/api\/games\/\d+\/broken/.test(url)) {
      const id = Number(url.split("/")[3]);
      brokenIds = init?.method === "PUT" ? [...brokenIds, id] : brokenIds.filter((f) => f !== id);
      return new Response(null, { status: 204 });
    }
    if (url.startsWith("/api/favorites")) return json(favoriteIds.map((id) => game(id, id === 1 ? "Super Mario World" : "Zelda")));
    if (/^\/api\/games\/\d+\/controls/.test(url)) {
      if (init?.method === "POST") return json({ status: "found", origin: controlsSourced ? "sourced" : "written",
        sources: controlsSourced ? [{ source: "strategywiki", page: "Super Mario World/Controls",
          url: "https://strategywiki.org/wiki/Super_Mario_World/Controls" }] : null, updated_at: "2026-10-17T10:00:00Z",
        can_generate: true, notes: { fr: "Haut + B : uppercut.", en: "Up + B: uppercut.", es: "Arriba + B: gancho." },
        controls: [{ button: "dpad", fr: "Se déplacer", en: "Move", es: "Moverse" },
          { button: "b", fr: "Coup de poing", en: "Punch", es: "Puñetazo" }] });
      if (init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as { controls: { button: string; text: string }[]; notes: string };
        return json({ status: "found", origin: "edited", updated_at: "2026-10-17T10:00:00Z", can_generate: true, notes: null,
          controls: body.controls.map((c) => ({ button: c.button, fr: c.text, en: c.text, es: c.text })) });
      }
      return json({ status: "none", origin: null, controls: [], notes: null, updated_at: null, can_generate: true });
    }
    if (/^\/api\/games\/\d+\/video/.test(url)) return json({
      status: "no_key", query: "Super Mario World SNES gameplay", videos: [],
      search_url: "https://www.youtube.com/results?search_query=Super+Mario+World+SNES+gameplay",
    });
    if (url.startsWith("/api/games/")) return json({ ...game(1, "Super Mario World"), ...sheetImages, favorite: favoriteIds.includes(1), broken: brokenIds.includes(1), players: 2, players_link: false, release_year: 1990, release_date: "1990-11-21",
      publisher: "Nintendo", developer: "Nintendo EAD", franchise: "Mario", description: "Mario's quest to save the princess.",
      descriptions: { fr: { text: "Mario part sauver la princesse.", origin: "translated" } },
      info_url: "http://www.gamefaqs.com/snes/519824-super-mario-world", remote_path: "/mnt/mmc/Roms/SFC/Super Mario World (USA).smc", image_relpath: null, possible_duplicates: [], history: [{ scan_run_id: 1, change: "added", old_size: null, new_size: 1, old_mtime: null, new_mtime: null, run_started_at: "2026-10-16T10:00:00Z" }] });
    if (url.startsWith("/api/games")) {
      const q = new URL(url, "http://x").searchParams.get("q");
      const fav = new URL(url, "http://x").searchParams.get("favorite") === "true";
      const items = [game(1, "Super Mario World"), game(2, "Zelda")]
        .filter((g) => (!q || g.title.toLowerCase().includes(q)) && (!fav || favoriteIds.includes(g.id)));
      return json({ page: { total: items.length, offset: 0, limit: 120 }, items });
    }
    return json({ error: { code: "not_found", message: "?" } }, 404);
  });
}

function Loc() {
  return <output data-testid="loc">{useLocation().search}</output>;
}

function renderAt(path: string) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
        <Loc />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  savedDescription = null;
  cheatsReady = false;
  installedCheat = null;
  localStorage.removeItem("agm-recent-searches");
  localStorage.removeItem("romkade-assistant-name");
  localStorage.removeItem("romkade-assistant-hidden");
  systemCaps = null;
  calls = [];
  bodies = [];
  deviceOnline = true;
  playingId = null;
  shots = [shot("20261019-203001.png"), shot("20261019-203000.png")];
  favoriteIds = [];
  brokenIds = [];
  hostKeyTrusted = true;
  relayToken = "";
  assistantBodies = [];
  assistantAction = null;
  sessionStorage.clear();
  assistant.reset();
  knowledgeJob = { running: false, total: 0, done: 0, found: 0, current: null, stopping: false };
  llm = { ...NO_LLM };
  volume = { percent: 60, muted: false };
  playAlerts = [];
  vi.stubGlobal("fetch", mockFetch());
  // Comme Chrome : scrollIntoView renvoie une promesse (un effet qui la renvoyait faisait planter toute la page).
  Element.prototype.scrollIntoView = function () { return Promise.resolve() as unknown as void; };
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} unobserve() {} });
  Element.prototype.getBoundingClientRect = function () {
    return { width: 1000, height: 800, top: 0, left: 0, right: 1000, bottom: 800, x: 0, y: 0, toJSON() {} } as DOMRect;
  };
});
afterEach(() => vi.unstubAllGlobals());

describe("Bibliothèque", () => {
  it("propose d'abord de choisir une console, puis montre ses jeux", async () => {
    renderAt("/bibliotheque");
    const card = await screen.findByRole("button", { name: /Super Nintendo/ });
    expect(screen.getByRole("region", { name: "Nintendo" })).toContainElement(card);
    expect(calls.some((c) => c.startsWith("/api/games"))).toBe(false);
    await userEvent.click(card);
    // Étape 2 : le genre, en cartes
    expect(await screen.findByRole("heading", { level: 1, name: "Super Nintendo" })).toBeInTheDocument();
    expect(screen.getByTestId("loc").textContent).toBe("?platform=SFC");
    expect(await screen.findByRole("button", { name: /Plateforme/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Tous les genres/ }));
    expect(await screen.findByText("Super Mario World")).toBeInTheDocument();
    expect(screen.getByTestId("loc").textContent).toBe("?platform=SFC&all=1");
    await userEvent.click(screen.getByRole("button", { name: "Genres" }));
    expect(await screen.findByRole("button", { name: /Sport/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Consoles" }));
    expect(await screen.findByRole("button", { name: /Tous les jeux/ })).toBeInTheDocument();
    expect(screen.getByTestId("loc").textContent).toBe("");
  });

  it("choisit un genre par sa carte, puis l'ajuste avec le filtre", async () => {
    renderAt("/bibliotheque?platform=SFC");
    await userEvent.click(await screen.findByRole("button", { name: /Plateforme/ }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("?platform=SFC&genre=plateforme"));
    await waitFor(() => expect(calls.some((c) => c.includes("genre=plateforme"))).toBe(true));
    expect(await screen.findByRole("heading", { level: 1, name: "Super Nintendo" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^Plateforme/ }));
    await userEvent.click(await screen.findByRole("checkbox", { name: /Sport/ }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("?platform=SFC&genre=plateforme&genre=sport"));
  });

  it("sans clé YouTube, la bande-annonce mène directement à la recherche YouTube", async () => {
    renderAt("/bibliotheque?all=1");
    const link = await screen.findByRole("link", { name: "Bande-annonce : Super Mario World" });
    expect(link).toHaveAttribute("href", "https://www.youtube.com/results?search_query=Super+Mario+World+SNES+gameplay");
    expect(link).toHaveAttribute("target", "_blank");
    await userEvent.click(await screen.findByText("Super Mario World"));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("link", { name: /Bande-annonce/ }))
      .toHaveAttribute("href", "https://www.youtube.com/results?search_query=Super+Mario+World+SNES+gameplay");
  });

  it("fiche : titre puis console, diaporama jaquette puis image de la carte, bande-annonce et source dessous", async () => {
    sheetImages = { boxart_url: "/api/games/1/boxart", image_url: "/api/games/1/image" };
    try {
      renderAt("/bibliotheque?all=1");
      await userEvent.click(await screen.findByText("Super Mario World"));
      const dialog = await screen.findByRole("dialog");
      const title = await within(dialog).findByRole("heading", { name: "Super Mario World" });
      expect(within(dialog).getByText("1 à 2 joueurs")).toBeInTheDocument();  // sous le titre, à côté de la console
      const gallery = within(dialog).getByRole("region", { name: "Images du jeu" });
      expect(title.compareDocumentPosition(gallery) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(within(gallery).getByRole("group", { name: "Jaquette, 1 sur 2" })).toBeInTheDocument();
      expect(within(dialog).getByRole("link", { name: "libretro-thumbnails" })).toBeInTheDocument();
      await userEvent.click(within(gallery).getByRole("button", { name: "Image suivante" }));
      expect(within(gallery).getByRole("group", { name: "Image de la carte, 2 sur 2" })).toBeInTheDocument();
      expect(within(dialog).queryByRole("link", { name: "libretro-thumbnails" })).not.toBeInTheDocument();
      const trailer = within(dialog).getByRole("link", { name: /Bande-annonce/ });
      expect(trailer).not.toHaveClass("button");
      expect(gallery.compareDocumentPosition(trailer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    } finally {
      sheetImages = {};
    }
  });

  it("le logo de la barre latérale mène au tableau de bord ; romkade.com sous Documentation", async () => {
    renderAt("/bibliotheque?all=1");
    expect(await screen.findByRole("link", { name: "ROMKADE Manager, tableau de bord" })).toHaveAttribute("href", "/");
    const site = screen.getByRole("link", { name: /romkade\.com/ });
    expect(site).toHaveAttribute("href", "https://romkade.com");
    expect(screen.getByRole("link", { name: /^Documentation/ }).compareDocumentPosition(site) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("affiche tous les jeux et filtre à la frappe", async () => {
    renderAt("/bibliotheque");
    await userEvent.click(await screen.findByRole("button", { name: /Tous les jeux/ }));
    expect(await screen.findByText("Super Mario World")).toBeInTheDocument();
    expect(screen.getByText("2 jeux")).toBeInTheDocument();
    // Une seule recherche, dans la barre du haut : mêmes suggestions qu'ailleurs, et la liste affichée est filtrée.
    expect(screen.getAllByRole("combobox", { name: "Rechercher un jeu" })).toHaveLength(1);
    await userEvent.type(screen.getByRole("combobox", { name: "Rechercher un jeu" }), "zel");
    expect(await screen.findByRole("option", { name: /Super Mario World/ })).toBeInTheDocument();
    expect(calls.some((c) => c.startsWith("/api/search?q=zel"))).toBe(true);
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByText("Super Mario World")).not.toBeInTheDocument());
    expect(screen.getByText("Zelda")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("?all=1&q=zel"));
    expect(calls.some((c) => c.includes("/api/games?q=zel"))).toBe(true);
  });

  it("ouvre la fiche avec les informations du jeu : genre, drapeaux, sortie, éditeur, résumé", async () => {
    renderAt("/bibliotheque?all=1");
    await userEvent.click(await screen.findByText("Super Mario World"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("/mnt/mmc/Roms/SFC/Super Mario World (USA).smc")).toBeInTheDocument();
    const info = within(dialog).getByRole("region", { name: "Informations sur le jeu" });
    expect(within(info).getByText("Plateforme")).toBeInTheDocument();
    expect(within(info).getByText("🇺🇸")).toBeInTheDocument();
    expect(within(info).getByText("21 novembre 1990")).toBeInTheDocument();
    const publisher = within(info).getByRole("link", { name: "Nintendo" });
    expect(publisher).toHaveAttribute("href", "https://fr.wikipedia.org/w/index.php?search=Nintendo&go=Go");
    expect(within(info).getByText("Mario part sauver la princesse.")).toBeInTheDocument();  // en français, par Claude
    expect(within(info).getByText("traduit par IA")).toBeInTheDocument();
    expect(within(info).getByRole("link", { name: /Fiche complète sur GameFAQs/ })).toBeInTheDocument();
  });

  it("propose les sous-genres du genre choisi et filtre dessus", async () => {
    renderAt("/bibliotheque?genre=sport&all=1");
    const chips = await screen.findByRole("group", { name: "Sous-genres de Sport" });
    expect(within(chips).getByRole("button", { name: /Tous\s*7/ })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(within(chips).getByRole("button", { name: /Golf\s*4/ }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toContain("sub=sport.golf"));
    await waitFor(() => expect(calls.some((c) => c.includes("subgenre=sport.golf"))).toBe(true));
  });

  it("garde les filtres dans l'URL", async () => {
    renderAt("/bibliotheque?platform=SFC&all=1&view=table");
    expect(await screen.findByRole("table")).toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.includes("platform=SFC"))).toBe(true));
    expect(screen.getByRole("heading", { level: 1, name: "Super Nintendo" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Console" })).not.toBeInTheDocument();
  });
});

describe("Jeu en cours", () => {
  it("remplace « Jouer sur la console » par le bandeau quand le jeu tourne", async () => {
    playingId = 1;
    renderAt("/bibliotheque?all=1");
    await userEvent.click(await screen.findByText("Super Mario World"));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("En cours sur la console")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /Jouer sur la console/ })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Quitter le jeu/ })).toBeInTheDocument();
  });
});

describe("Jouer avec une manette branchée", () => {
  it("« Qui joue ? » : une manette par joueur (celle d'un autre joueur est grisée), enregistrées puis le jeu lancé", async () => {
    renderAt("/bibliotheque?all=1");
    await userEvent.click(await screen.findByText("Super Mario World"));
    const dialog = await screen.findByRole("dialog");
    const who = await within(dialog).findByRole("group", { name: "Qui joue ?" });
    // Les 4 joueurs, comme sur la page Manettes, avec la config enregistrée : joueur 2 sur la 8BitDo, joueur 3 sur
    // les boutons de la console. La 8BitDo est grisée pour le joueur 1 : le joueur 2 la libère, le joueur 1 la prend.
    expect(within(who).getByLabelText("Joueur 1")).toHaveDisplayValue("Aucune manette");
    expect(within(who).getByLabelText("Joueur 3")).toHaveDisplayValue("Boutons de la console");
    expect(within(who).getByLabelText("Joueur 4")).toHaveDisplayValue("Aucune manette");
    expect(within(within(who).getByLabelText("Joueur 1")).getByRole("option", { name: "8BitDo Pro 2 · manette n°1 — joueur 2" })).toBeDisabled();
    await userEvent.selectOptions(within(who).getByLabelText("Joueur 2"), "Aucune manette");
    await userEvent.selectOptions(within(who).getByLabelText("Joueur 1"), "8BitDo Pro 2 · manette n°1");
    await userEvent.click(within(dialog).getByRole("button", { name: /Jouer sur la console/ }));
    await waitFor(() => expect(bodies.some((b) => b.url === "/api/games/1/launch")).toBe(true));
    const put = bodies.findIndex((b) => b.url === "/api/players");
    expect(bodies[put]).toEqual({ url: "/api/players", players: [1, 2, 0, 3] });
    expect(put).toBeLessThan(bodies.findIndex((b) => b.url === "/api/games/1/launch"));
  });
});

describe("Effacer et filtrer le temps de jeu", () => {
  it("efface le temps d'un jeu, tout le temps de jeu, et filtre sur une période", async () => {
    renderAt("/temps-de-jeu");
    await userEvent.click(await screen.findByRole("button", { name: "Effacer le temps de jeu de Super Mario World" }));
    const one = screen.getByRole("group", { name: "Effacer le temps de jeu de Super Mario World ?" });
    await userEvent.click(within(one).getByRole("button", { name: "Effacer" }));
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/play/reset", games: [{ key: "id:1", ra_seconds: 3600 }] }));

    await userEvent.click(screen.getByRole("button", { name: /Tout effacer/ }));
    const all = screen.getByRole("group", { name: /Effacer tout le temps de jeu/ });
    await userEvent.click(within(all).getByRole("button", { name: "Effacer" }));
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/play/reset-all", games: [{ key: "id:1", ra_seconds: 3600 }] }));

    fireEvent.change(screen.getByLabelText("Du"), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText("Au"), { target: { value: "2026-10-10" } });
    await waitFor(() => expect(calls.some((c) => c.includes("/api/play/stats") && c.includes("start=2026-10-01") && c.includes("end=2026-10-10"))).toBe(true));
    expect(await screen.findByText(/seules les parties suivies par Game Manager comptent/)).toBeInTheDocument();
  });
});

describe("Connexion en étapes", () => {
  it("montre les étapes, le champ de l'authentification choisie, et enregistre le mot de passe avec la console", async () => {
    hostKeyTrusted = false;
    renderAt("/parametres");
    const steps = await screen.findByRole("navigation", { name: "Mise en route de la connexion" });
    expect(within(steps).getByRole("link", { name: /La console.*fait/ })).toBeInTheDocument();
    expect(within(steps).getByRole("link", { name: /Identifier la console.*étape en cours/ })).toBeInTheDocument();
    // Une étape faite reste une action claire : résumé de ce qui est réglé, « Modifier », lien vers sa section.
    const first = within(steps).getByRole("link", { name: /La console/ });
    expect(first).toHaveTextContent("192.168.86.242 · root · mot de passe");
    expect(first).toHaveTextContent("Modifier");
    expect(first).toHaveAttribute("href", "#conn-h");
    expect(within(steps).getByRole("link", { name: /Tester la connexion/ })).toHaveTextContent("Faire le test");
    const form = (await screen.findByRole("heading", { name: /La console/ })).closest("form")!;
    expect(within(form).getByLabelText("Remplacer le mot de passe")).toBeInTheDocument();
    await userEvent.click(within(form).getByRole("radio", { name: /Clé SSH/ }));
    expect(within(form).queryByLabelText("Remplacer le mot de passe")).not.toBeInTheDocument();
    expect(within(form).getByLabelText("Chemin de la clé privée")).toBeInTheDocument();
    await userEvent.click(within(form).getByRole("radio", { name: /Mot de passe/ }));
    await userEvent.type(within(form).getByLabelText("Remplacer le mot de passe"), "s3cret");
    await userEvent.click(within(form).getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/settings/password", password: "s3cret" }));
  });
});

describe("Nouvelle console : clé à approuver", () => {
  it("lit l'empreinte tout de suite et l'approuve d'un clic", async () => {
    hostKeyTrusted = false;
    renderAt("/parametres");
    const panel = (await screen.findByRole("heading", { name: /Identité de la console/ })).closest("section")!;
    expect(await within(panel).findByText("SHA256:abc")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Approuver cette clé" }));
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/device/host-key/trust", fingerprint: "SHA256:abc" }));
    expect(await within(panel).findByText("Approuvée")).toBeInTheDocument();
  });

  it("l'erreur de clé inconnue mène à l'approbation", async () => {
    const { ApiError } = await import("../api/client");
    const { ErrorNotice } = await import("../components/ui");
    render(<MemoryRouter><ErrorNotice error={new ApiError(409, "host_key_unknown", "La clé de cette console n'est pas encore approuvée")} /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "Vérifier et approuver la clé de la console" })).toHaveAttribute("href", "/parametres#hk");
  });
});

describe("Première connexion depuis le tableau de bord", () => {
  it("guide étape par étape, de la clé à approuver jusqu'au test, sans proposer de synchroniser", async () => {
    hostKeyTrusted = false;
    deviceOnline = false;
    const base = mockFetch();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => String(input).startsWith("/api/catalog/status")
      ? new Response(JSON.stringify({ ...status, synced: false }), { headers: { "Content-Type": "application/json" } })
      : base(input, init)));
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Connecte ta console" })).toBeInTheDocument();
    expect(await screen.findByText("Étape 2 sur 3 : Identifier la console")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Synchroniser/ })).toBeNull();
    const panel = (await screen.findByRole("heading", { name: /Identité de la console/ })).closest("section")!;
    expect(await within(panel).findByText("SHA256:abc")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Approuver cette clé" }));
    expect(await screen.findByText("Étape 3 sur 3 : Tester la connexion")).toBeInTheDocument();
    await waitFor(() => expect(calls).toContain("/api/device/diagnose"));
  });

  it("cherche la console tout seul, la propose, et reprend son adresse quand on confirme", async () => {
    deviceOnline = false;
    const base = mockFetch();
    const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/catalog/status")) return json({ ...status, synced: false });
      if (url === "/api/settings") return json({ host: "", port: 22, username: "root", auth_method: "password", key_path: null,
        roms_root: "/mnt/mmc/Roms", connect_timeout: 8, system: "auto", has_password: false, host_key_trusted: false });
      if (url.startsWith("/api/device/discover")) {
        calls.push(url);
        return json({ scanned: false, consoles: [
          { host: "192.168.86.242", name: "anbernic", banner: "SSH-2.0-OpenSSH_8.9p1", likely: true },
          { host: "192.168.86.240", name: "mac.lan", banner: "SSH-2.0-OpenSSH_10.2", likely: false },
        ] });
      }
      return base(input, init);
    }));
    renderAt("/");
    expect(await screen.findByText("Étape 1 sur 3 : La console")).toBeInTheDocument();
    const found = (await screen.findByText("anbernic · 192.168.86.242")).closest("li")!;
    expect(screen.getByText("mac.lan · 192.168.86.240")).toBeInTheDocument();
    await userEvent.click(within(found).getByRole("button", { name: "C'est ma console" }));
    expect(screen.getByLabelText("Adresse IP ou nom")).toHaveValue("192.168.86.242");
    expect(within(found).getByText(/Adresse reprise/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Chercher sur tout le réseau" }));
    await waitFor(() => expect(calls).toContain("/api/device/discover?scan=true"));
  });
});

describe("Paramètres : assistant et connaissances", () => {
  it("onglet Assistant IA : les trois étapes d'abord (état et déconnexion à l'étape 3), puis le prénom (Duke, modifiable) et l'affichage", async () => {
    renderAt("/parametres/ia");
    expect(await screen.findByRole("link", { name: /^Assistant IA/ })).toHaveAttribute("aria-current", "page");
    const headings = (await screen.findAllByRole("heading", { level: 2 })).map((h) => h.textContent ?? "");
    const order = ["Type d'IA", "Connexion et modèle", "Tester la connexion", "Prénom et affichage"].map((x) => headings.findIndex((h) => h.includes(x)));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    const steps = screen.getByRole("navigation", { name: "Mise en route de l'assistant IA" });
    expect(within(steps).getByRole("link", { name: /Type d'IA/ })).toHaveAttribute("href", "#ai-1");
    expect(within(steps).getByRole("link", { name: /Tester la connexion/ })).toHaveTextContent("Faire le test");
    expect(screen.getByRole("link", { name: /Connaissances de l'assistant/ })).toHaveAttribute("href", "/parametres/catalogue");
    expect(screen.queryByRole("heading", { name: /Descriptions des jeux/ })).not.toBeInTheDocument();  // dans Connaissances
    // Prénom : Duke par défaut, aucune liste proposée ; un simple champ, et la bulle prend le nouveau prénom.
    expect(screen.getByRole("button", { name: /^Duke$/ })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /Axel|Nova|Mario/ })).not.toBeInTheDocument();
    const field = screen.getByRole("textbox", { name: "Prénom de l'assistant" });
    expect(field).toHaveValue("Duke");
    await userEvent.clear(field);
    await userEvent.type(field, "Luna");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    expect(screen.getByRole("button", { name: /^Luna$/ })).toBeInTheDocument();
    // La bulle peut être masquée.
    const show = screen.getByRole("checkbox", { name: /Afficher la bulle de l'assistant IA/ });
    expect(show).toBeChecked();
    await userEvent.click(show);
    expect(screen.queryByRole("button", { name: /^Luna$/ })).not.toBeInTheDocument();
  });

  it("l'ancienne adresse de Contenu IA mène aux connaissances, avec les descriptions des jeux", async () => {
    renderAt("/parametres/descriptions");
    expect(await screen.findByRole("heading", { name: /Connaissances de l'assistant/ })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /Descriptions des jeux/ })).toBeInTheDocument();
  });

  it("connaissances : lance la récupération, puis un seul jeu : pages enregistrées et passages pour une question", async () => {
    renderAt("/parametres/catalogue");
    expect(await screen.findByRole("link", { name: /^Catalogue$/ })).toBeInTheDocument();
    const panel = (await screen.findByRole("heading", { name: /Connaissances de l'assistant/ })).closest("section")!;
    expect(within(panel).getByText(/ce n'est pas un simple essai/)).toBeInTheDocument();
    expect(await within(panel).findByText(/1 jeux documentés sur 2/)).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: /Tout récupérer à nouveau \(2 jeux/ })).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: /Tout récupérer à nouveau/ }));
    await waitFor(() => expect(calls).toContain("/api/knowledge/start?refresh=true"));
    knowledgeJob = { running: false, total: 0, done: 0, found: 0, current: null, stopping: false };
    await userEvent.click(await within(panel).findByRole("button", { name: /Récupérer pour le jeu restant/ }));
    expect(await within(panel).findByText(/Récupération en cours : 0 sur 1/)).toBeInTheDocument();

    await userEvent.type(within(panel).getByRole("searchbox", { name: "Jeu" }), "mario");
    await userEvent.click(await within(panel).findByRole("button", { name: /Super Mario World/ }));
    await userEvent.click(await within(panel).findByRole("button", { name: /^Récupérer$/ }));
    expect(await within(panel).findByRole("link", { name: /Wikipédia \(en\) · Super Mario World/ })).toHaveAttribute("href", "https://en.wikipedia.org/wiki/Super_Mario_World");
    await userEvent.type(within(panel).getByRole("textbox", { name: "Question de test" }), "castle");
    await userEvent.click(within(panel).getByRole("button", { name: /Voir les passages trouvés/ }));
    expect(await within(panel).findByText(/Use the cape to fly/)).toBeInTheDocument();
  });
});

describe("Assistant de jeu", () => {
  it("propose de discuter du jeu ouvert, puis répond en direct avec ses sources", async () => {
    llm = { ...llm, provider: "local", model: "qwen2.5:7b", base_url: "http://localhost:11434/v1" };
    renderAt("/bibliotheque?all=1");
    await userEvent.click(await screen.findByText("Super Mario World"));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: /^Duke$/ }));
    const panel = within(dialog).getByRole("region", { name: "Duke" });
    expect(within(panel).getByText("Tu regardes Super Mario World. Discuter de ce jeu ?")).toBeInTheDocument();
    // La proposition se ferme d'une croix ; le jeu reste au choix dans l'en-tête du panneau.
    await userEvent.click(within(panel).getByRole("button", { name: "Fermer la proposition" }));
    expect(within(panel).queryByText("Tu regardes Super Mario World. Discuter de ce jeu ?")).not.toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Super Mario World" }));
    expect(within(panel).getByRole("button", { name: "Super Mario World" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.type(within(panel).getByRole("textbox", { name: "Ta question" }), "Je bloque au château");
    await userEvent.click(within(panel).getByRole("button", { name: "Envoyer" }));
    expect(await within(panel).findByText(/Indice : utilise la cape\./)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: /StrategyWiki · CC BY-SA 4.0/ })).toHaveAttribute("href", "https://strategywiki.org/wiki/Super_Mario_World/Vanilla_Dome");
    expect(within(panel).getByText(/modèle local : rien ne quitte cet ordinateur/)).toBeInTheDocument();
    expect(assistantBodies[0]).toMatchObject({ scope: "game", game_id: 1, lang: "fr", name: "Duke",
      messages: [{ role: "user", content: "Je bloque au château" }] });
  });

  it("se replie et se déplie d'un chevron, sans perdre la conversation", async () => {
    renderAt("/");
    await userEvent.click(await screen.findByRole("button", { name: /^Duke$/ }));
    const panel = screen.getByRole("region", { name: "Duke" });
    expect(within(panel).getByRole("textbox", { name: "Ta question" })).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Replier" }));
    expect(within(panel).queryByRole("textbox", { name: "Ta question" })).not.toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Déplier" }));
    expect(within(panel).getByRole("textbox", { name: "Ta question" })).toBeInTheDocument();
  });

  it("propose une action sur la console et ne l'exécute qu'au clic", async () => {
    llm = { ...llm, provider: "local", model: "qwen2.5:7b", base_url: "http://localhost:11434/v1" };
    assistantAction = { kind: "set_volume", supported: true, system: "muOS", percent: 50, games: [] };
    renderAt("/");
    await userEvent.click(await screen.findByRole("button", { name: /^Duke$/ }));
    const panel = screen.getByRole("region", { name: "Duke" });
    await userEvent.click(await within(panel).findByRole("button", { name: "Mets le son à 50 %" }));
    expect(await within(panel).findByText("Mettre le son à 50 % ?")).toBeInTheDocument();
    expect(bodies.some((b) => b.url === "/api/volume")).toBe(false);  // rien avant le clic
    await userEvent.click(within(panel).getByRole("button", { name: /Appliquer/ }));
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/volume", percent: 50 }));
    expect(await within(panel).findByText("C'est fait.")).toBeInTheDocument();
  });
});

describe("Codes de triche (RetroArch)", () => {
  it("fiche : télécharge la base, affiche les codes de la version choisie et copie le fichier sur la console", async () => {
    renderAt("/bibliotheque?all=1");
    await userEvent.click(await screen.findByText("Super Mario World"));
    const dialog = await screen.findByRole("dialog");
    const section = (await within(dialog).findByRole("heading", { name: "Codes de triche" })).closest("section")!;
    await userEvent.click(within(section).getByRole("button", { name: /Télécharger les codes/ }));
    expect(await within(section).findByText("Vies infinies")).toBeInTheDocument();
    expect(within(section).getByText("7E0DBE:0")).toBeInTheDocument();
    expect(within(section).queryByText("Code 9")).not.toBeInTheDocument();  // 8 premiers, puis « Tout afficher »
    await userEvent.click(within(section).getByRole("button", { name: "Tout afficher (10)" }));
    expect(within(section).getByText("Code 9")).toBeInTheDocument();
    await userEvent.selectOptions(within(section).getByRole("combobox", { name: "Version" }), "1");
    expect(within(section).getByText("DD6A-1F0D")).toBeInTheDocument();
    await userEvent.click(within(section).getByRole("button", { name: "Copier sur la console" }));
    expect(await within(section).findByText(/Fichier copié dans le dossier des codes de RetroArch/)).toBeInTheDocument();
    expect(installedCheat).toBe("SNES/Super Mario World (USA) (Game Genie).cht");
  });

  it("paramètres : connaissances > codes de triche, téléchargement puis mise à jour", async () => {
    renderAt("/parametres/catalogue");
    const panel = (await screen.findByRole("heading", { name: "Codes de triche (RetroArch)" })).closest("section")!;
    expect(await within(panel).findByText(/Pas encore téléchargée/)).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: /Télécharger les codes/ }));
    expect(await within(panel).findByText(/fichiers de codes · mise à jour le/)).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: /Mettre à jour/ })).toBeInTheDocument();
  });
});

describe("Connaissances : descriptions d'un seul jeu", () => {
  it("montre la description de la fiche, propose celle de l'IA et ne la met dans la fiche qu'une fois validée", async () => {
    renderAt("/parametres/catalogue");
    const section = (await screen.findByRole("heading", { name: /Descriptions des jeux/ })).closest("section")!;
    await userEvent.type(await within(section).findByRole("searchbox", { name: "Jeu" }), "mario");
    await userEvent.click(await within(section).findByRole("button", { name: /Super Mario World/ }));
    expect(await within(section).findByText(/Mario part sauver la princesse\./)).toBeInTheDocument();
    await userEvent.click(within(section).getByRole("button", { name: /Proposer une description avec l'IA/ }));
    const draft = await within(section).findByRole("group", { name: /Proposition de l'IA/ });
    expect(within(draft).getByText(/Mario doit délivrer la princesse Peach\./)).toBeInTheDocument();
    expect(within(draft).getByText(/déjà une description : si tu valides, la proposition la remplace/)).toBeInTheDocument();
    expect(savedDescription).toBeNull();  // rien d'enregistré avant validation
    await userEvent.click(within(draft).getByRole("button", { name: /Mettre dans la fiche/ }));
    expect(await within(section).findByText("Description mise dans la fiche du jeu.")).toBeInTheDocument();
    expect(savedDescription).toMatchObject({ mode: "translate", texts: { fr: "Mario doit délivrer la princesse Peach." } });
  });
});

describe("Tri par année de sortie", () => {
  it("trie du plus ancien au plus récent et montre l'année dans le tableau", async () => {
    renderAt("/bibliotheque?all=1&sort=year&view=table");
    await waitFor(() => expect(calls.some((c) => c.startsWith("/api/games?") && c.includes("sort=year") && c.includes("order=asc"))).toBe(true));
    expect(await screen.findByRole("columnheader", { name: /Année/ })).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getByRole("button", { name: /Plus anciens d'abord/ })).toBeInTheDocument();
  });
});

describe("Favoris", () => {
  it("met un jeu en favori depuis sa fiche, le montre au tableau de bord et filtre la bibliothèque", async () => {
    renderAt("/");
    const section = await screen.findByRole("region", { name: "Mes favoris" });
    expect(await within(section).findByText(/Aucun favori pour l'instant/)).toBeInTheDocument();
    const added = screen.getByRole("region", { name: "Derniers ajouts" });
    await userEvent.click(await within(added).findByText("Super Mario World"));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: /Ajouter aux favoris/ }));
    expect(await within(dialog).findByRole("button", { name: /Dans mes favoris/ })).toHaveAttribute("aria-pressed", "true");
    expect(await within(section).findByText("Super Mario World")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(within(section).getByRole("link", { name: /Tous mes favoris/ }));
    expect(await screen.findByRole("heading", { level: 1, name: "Mes favoris" })).toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.startsWith("/api/games?") && c.includes("favorite=true"))).toBe(true));
    expect(await screen.findByText("Super Mario World")).toBeInTheDocument();
    expect(screen.queryByText("Zelda")).not.toBeInTheDocument();
  });
});

describe("Jeux qui ne fonctionnent pas", () => {
  it("signale un jeu depuis sa fiche, puis retire le signalement ; la bibliothèque les filtre", async () => {
    renderAt("/bibliotheque?all=1");
    await userEvent.click(await screen.findByText("Super Mario World"));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: /Ne fonctionne pas/ }));
    expect(await within(dialog).findByRole("button", { name: /Signalé : ne fonctionne pas/ })).toHaveAttribute("aria-pressed", "true");
    expect(within(dialog).getByText("Ne fonctionne pas sur cette console")).toBeInTheDocument();
    expect(calls).toContain("/api/games/1/broken");
    await userEvent.click(within(dialog).getByRole("button", { name: /Signalé : ne fonctionne pas/ }));
    expect(await within(dialog).findByRole("button", { name: /^Ne fonctionne pas$/ })).toHaveAttribute("aria-pressed", "false");
    expect(within(dialog).queryByText("Ne fonctionne pas sur cette console")).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: /Ne fonctionnent pas/ }));
    expect(await screen.findByRole("heading", { level: 1, name: "Jeux qui ne fonctionnent pas" })).toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.startsWith("/api/games?") && c.includes("broken=true"))).toBe(true));
  });
});

describe("Commandes du jeu", () => {
  it("demande les commandes à Claude puis les corrige à la main", async () => {
    renderAt("/bibliotheque?all=1");
    await userEvent.click(await screen.findByText("Super Mario World"));
    const dialog = await screen.findByRole("dialog");
    const section = (await within(dialog).findByRole("heading", { name: "Commandes" })).closest("section")!;
    await userEvent.click(within(section).getByRole("button", { name: /Demander à l'IA/ }));
    expect(await within(section).findByText("Coup de poing")).toBeInTheDocument();
    expect(within(section).getByText("Haut + B : uppercut.")).toBeInTheDocument();
    expect(within(section).getByText(/à vérifier en jeu/)).toBeInTheDocument();

    await userEvent.click(within(section).getByRole("button", { name: /Corriger/ }));
    const actions = within(section).getAllByRole("textbox", { name: "Action" });
    await userEvent.clear(actions[1]!);
    await userEvent.type(actions[1]!, "Tir");
    await userEvent.click(within(section).getByRole("button", { name: "Enregistrer" }));
    expect(await within(section).findByText("Tir")).toBeInTheDocument();
    expect(bodies.at(-1)).toMatchObject({ controls: [{ button: "dpad", text: "Se déplacer" }, { button: "b", text: "Tir" }] });
    expect(within(section).getByText("Corrigé à la main.")).toBeInTheDocument();
  });

  it("commandes rédigées d'après StrategyWiki : la source est citée avec son lien", async () => {
    controlsSourced = true;
    try {
      renderAt("/bibliotheque?all=1");
      await userEvent.click(await screen.findByText("Super Mario World"));
      const dialog = await screen.findByRole("dialog");
      const section = (await within(dialog).findByRole("heading", { name: "Commandes" })).closest("section")!;
      await userEvent.click(within(section).getByRole("button", { name: /Demander à l'IA/ }));
      expect(await within(section).findByText(/d'après :/)).toBeInTheDocument();
      expect(within(section).getByRole("link", { name: "StrategyWiki · Super Mario World/Controls" }))
        .toHaveAttribute("href", "https://strategywiki.org/wiki/Super_Mario_World/Controls");
    } finally {
      controlsSourced = false;
    }
  });
});

describe("Jeu en cours : volume dans la fiche", () => {
  it("règle le son depuis le bandeau de la fiche", async () => {
    playingId = 1;
    renderAt("/bibliotheque?all=1");
    await userEvent.click(await screen.findByText("Super Mario World"));
    const dialog = await screen.findByRole("dialog");
    const banner = (await within(dialog).findByText("En cours sur la console")).closest(".playing-banner") as HTMLElement;
    expect(await within(banner).findByRole("slider", { name: "Volume des jeux" })).toHaveValue("60");
  });
});

describe("Volume", () => {
  it("coupe, remet le son et règle le volume depuis le bloc du jeu en cours", async () => {
    playingId = 1;
    renderAt("/");
    const card = await screen.findByRole("region", { name: "Super Mario World" });
    const slider = await within(card).findByRole("slider", { name: "Volume des jeux" });
    expect(slider).toHaveValue("60");
    await userEvent.click(within(card).getByRole("button", { name: "Couper le son" }));
    expect(await within(card).findByText("son coupé")).toBeInTheDocument();
    expect(bodies.at(-1)).toEqual({ url: "/api/volume", muted: true });
    await userEvent.click(within(card).getByRole("button", { name: "Remettre le son" }));
    expect(await within(card).findByText("60 %")).toBeInTheDocument();
  });

  it("ouvre la fiche du jeu en cours en cliquant sur son titre", async () => {
    playingId = 1;
    renderAt("/");
    const card = await screen.findByRole("region", { name: "Super Mario World" });
    await userEvent.click(within(card).getByRole("button", { name: "Super Mario World" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("est aussi dans la barre du haut, hors du tableau de bord", async () => {
    playingId = 1;
    renderAt("/bibliotheque");
    expect(await screen.findByRole("slider", { name: "Volume des jeux" })).toBeInTheDocument();
  });
});

describe("Temps de jeu", () => {
  it("affiche le temps du jour, la jauge vers la limite et le temps par jeu", async () => {
    renderAt("/temps-de-jeu");
    expect(await screen.findByText("3 h 00")).toBeInTheDocument();
    expect(screen.getByText("encore 1 h 00 avant la limite de 4 h 00")).toBeInTheDocument();
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "10800");
    expect(screen.getAllByText("Super Mario World").length).toBeGreaterThan(0);
    expect(screen.getAllByText("2 h 00").length).toBe(2);  // par jeu et dans l'historique
  });

  it("affiche la pop-in d'alerte et la ferme", async () => {
    playAlerts = [{ id: 1, created_at: "2026-10-16T12:00:00Z", minutes: 240, scope: "session", game_title: "Super Mario World" }];
    renderAt("/");
    const alert = await screen.findByRole("alertdialog");
    expect(within(alert).getByText("Ça fait 4 h 00 que tu joues")).toBeInTheDocument();
    await userEvent.click(within(alert).getByRole("button", { name: "OK, compris" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });
});

describe("Sauvegardes", () => {
  it("explique comment sauvegarder et liste les sauvegardes du jeu", async () => {
    renderAt("/sauvegardes");
    expect(await screen.findByText("Super Mario World")).toBeInTheDocument();
    expect(screen.getByText("Instantanée 1")).toBeInTheDocument();
    expect(await screen.findByText("sauvegarder dans l'emplacement choisi")).toBeInTheDocument();
    expect(screen.getAllByText("R1")[0]!.tagName).toBe("KBD");
    await userEvent.click(screen.getByRole("button", { name: "Supprimer" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Une copie est gardée sur l'ordinateur/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Supprimer" }));
    await waitFor(() => expect(bodies.some((b) => b.url === "/api/saves/delete")).toBe(true));
  });
});

describe("Langue", () => {
  it("change de langue avec les drapeaux en haut à droite", async () => {
    renderAt("/");
    const choose = async (current: string, target: RegExp) => {
      await userEvent.click(screen.getByRole("button", { name: current }));
      await userEvent.click(await screen.findByRole("button", { name: target }));
    };
    await screen.findByRole("button", { name: "Langue" });
    await choose("Langue", /English/);
    expect(await screen.findByRole("link", { name: /Library/ })).toBeInTheDocument();
    await choose("Language", /Español/);
    expect(await screen.findByRole("link", { name: /Biblioteca/ })).toBeInTheDocument();
    await choose("Idioma", /Français/);
    expect(await screen.findByRole("link", { name: /Bibliothèque/ })).toBeInTheDocument();
  });
});

describe("Paramètres", () => {
  it("teste la connexion étape par étape et explique le blocage « Réseau local » de macOS", async () => {
    renderAt("/parametres");
    const tabs = await screen.findByRole("navigation", { name: "Rubriques des paramètres" });
    expect(within(tabs).getByRole("link", { name: /Connexion/ })).toHaveAttribute("aria-current", "page");
    await userEvent.click(within(tabs).getByRole("link", { name: /Test de connexion/ }));
    const panel = (await screen.findByRole("heading", { name: "Tester la connexion" })).closest("section")!;
    await userEvent.click(within(panel).getByRole("button", { name: /Tester/ }));
    expect(await within(panel).findByText("Une étape a échoué : les suivantes n'ont pas été testées.")).toBeInTheDocument();
    expect(within(panel).getByText(/Réseau local, active l'application qui a lancé le serveur/)).toBeInTheDocument();
    expect(within(panel).getAllByText("Non testé")).toHaveLength(5);
  });
});

describe("Connexion à une IA", () => {
  it("sans IA : Claude se connecte avec la seule clé, vérifiée automatiquement", async () => {
    renderAt("/parametres/ia");
    expect((await screen.findAllByText("Aucune IA connectée")).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("radio", { name: /Service en ligne/ }));  // étape 1
    await userEvent.click(screen.getByRole("radio", { name: /Claude \(Anthropic\)/ }));  // étape 2
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/settings/llm", provider: "anthropic" }));
    expect((await screen.findAllByText("Ajoute la clé d'API de Claude (Anthropic) ci-dessous.")).length).toBeGreaterThan(0);
    const key = screen.getByLabelText("Clé d'API Claude (Anthropic)");
    await userEvent.type(key, "sk-ant-test");
    expect(key).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: "Afficher" }));
    expect(key).toHaveAttribute("type", "text");
    await userEvent.click(screen.getByRole("button", { name: /trousseau/ }));
    await waitFor(() => expect(bodies.some((b) => b.url === "/api/settings/llm/key" && b.api_key === "sk-ant-test")).toBe(true));
    expect((await screen.findAllByText("Connectée : Claude (Anthropic) · claude-opus-5-5")).length).toBeGreaterThan(0);
    expect(calls).toContain("/api/settings/llm/test");
  });

  it("modèle local : adresse LM Studio, modèle de la liste, guide d'installation", async () => {
    renderAt("/parametres/ia");
    await userEvent.click(await screen.findByRole("radio", { name: /Modèle local ou service compatible OpenAI/ }));
    expect(await screen.findByRole("link", { name: /Guide : installer un LLM local/ }))
      .toHaveAttribute("href", "https://github.com/RomKade/romkade-manager/blob/main/docs/local-llm.fr.md");
    await userEvent.click(screen.getByRole("button", { name: "LM Studio" }));
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/settings/llm", provider: "local", base_url: "http://localhost:1234/v1", model: null }));
    await userEvent.click(await screen.findByRole("option", { name: "qwen2.5:7b" }));
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/settings/llm", provider: "local", model: "qwen2.5:7b", base_url: "http://localhost:1234/v1" }));
    expect((await screen.findAllByText(/Connectée : Ollama, LM Studio, autre… · qwen2.5:7b/)).length).toBeGreaterThan(0);
  });
});

describe("Système de la console", () => {
  it("met en avant ce que la console sait faire, regroupé, avant le choix du système et l'horloge", async () => {
    systemCaps = { launch: true, resume_slot: false, quit: true, save_state: true, now_playing: true, saves: true,
      retroarch_logs: true, bluetooth: false, bluetooth_audio: false, players: true, volume: true, clock: true };
    renderAt("/parametres/systeme");
    const panel = (await screen.findByRole("heading", { name: "Ce que tu peux faire avec cette console" })).closest("section")!;
    expect(within(panel).getByRole("heading", { name: /Jeux/ })).toBeInTheDocument();
    expect(within(panel).getByRole("heading", { name: /Son/ })).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Choisir la manette de chaque joueur" })).toHaveAttribute("href", "/manettes");
    expect(within(panel).getByText("Bluetooth").closest("li")).toHaveClass("caps__no");
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings.indexOf("Ce que tu peux faire avec cette console")).toBeLessThan(headings.findIndex((h) => /Date et heure/.test(h ?? "")));
  });

  it("Android : pas de réglage de l'heure de la console", async () => {
    systemCaps = { launch: true, resume_slot: false, quit: true, save_state: true, now_playing: true, saves: true,
      retroarch_logs: false, bluetooth: false, bluetooth_audio: false, players: false, volume: false, clock: false };
    renderAt("/parametres/systeme");
    await screen.findByRole("heading", { name: "Ce que tu peux faire avec cette console" });
    expect(screen.queryByRole("heading", { name: /Date et heure/ })).not.toBeInTheDocument();
  });
});

describe("Conditions d'utilisation et version", () => {
  it("montre le bandeau au premier lancement, mène aux conditions, puis disparaît", async () => {
    localStorage.removeItem("romkade-terms-v1");
    renderAt("/");
    const notice = await screen.findByRole("region", { name: "Conditions d'utilisation" });
    expect(within(notice).getByText(/ne fournit aucun jeu/)).toBeInTheDocument();
    await userEvent.click(within(notice).getByRole("link", { name: /Lire les conditions/ }));
    expect(await screen.findByRole("heading", { name: "Responsabilité" })).toBeInTheDocument();
    expect(screen.getByText(/carte mémoire corrompue/)).toBeInTheDocument();
    await userEvent.click(within(notice).getByRole("button", { name: "J'ai compris" }));
    expect(screen.queryByRole("region", { name: "Conditions d'utilisation" })).not.toBeInTheDocument();
    expect(localStorage.getItem("romkade-terms-v1")).toBe("1");
  });

  it("affiche le logo, la version et le lien des conditions", async () => {
    renderAt("/parametres/a-propos");
    expect(await screen.findByText(/^Version \d+\.\d+\.\d+$/)).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "ROMKADE Manager" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Conditions d'utilisation" })[0]).toHaveAttribute("href", "/conditions");
    expect(screen.getByRole("link", { name: /^v\d/ })).toHaveAttribute("href", "/parametres/a-propos");
  });
});

describe("Barre latérale", () => {
  it("montre la recherche de la console, puis hors ligne avec Réessayer ; lien vers la documentation", async () => {
    deviceOnline = false;
    renderAt("/");
    const card = await screen.findByRole("region", { name: /État de la console/ });
    expect(within(card).getByText("Recherche de la console…")).toBeInTheDocument();
    const retry = await within(card).findByRole("button", { name: "Réessayer maintenant" });
    expect(within(card).getByText("Hors ligne")).toBeInTheDocument();
    await userEvent.click(retry);
    expect(calls.filter((c) => c.startsWith("/api/device/status")).length).toBeGreaterThan(1);
    expect(screen.getByRole("link", { name: /Documentation/ }))
      .toHaveAttribute("href", "https://romkade.com/docs/fr/");
  });
});

describe("Sources et crédits", () => {
  it("cite chaque source avec un lien, et le dépôt GitHub", async () => {
    renderAt("/parametres/credits");
    const panel = (await screen.findByRole("heading", { name: "Sources et crédits" })).closest("section")!;
    expect(within(panel).getByRole("link", { name: /libretro-thumbnails/ })).toHaveAttribute("href", "https://github.com/libretro-thumbnails/libretro-thumbnails");
    expect(within(panel).getByRole("link", { name: /OpenVGDB/ })).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(within(panel).getByText("CC BY 4.0")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: /sur GitHub/ })).toHaveAttribute("href", "https://github.com/RomKade/romkade-manager");
  });
});

describe("Date et heure", () => {
  it("montre le retard de la console et la met à l'heure de l'ordinateur", async () => {
    renderAt("/parametres/systeme");
    const panel = (await screen.findByRole("heading", { name: "Date et heure de la console" })).closest("section")!;
    expect(await within(panel).findByText("En retard de 4 ans")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: /Mettre à l'heure de l'ordinateur/ }));
    expect(await within(panel).findByText("La console est à l'heure.")).toBeInTheDocument();
    expect(bodies.at(-1)).toMatchObject({ url: "/api/device/clock/sync" });
  });
});

describe("Manettes", () => {
  it("sans jeu en cours, rend la main à la console (l'ancien joueur 1 l'échange) puis ouvre la bibliothèque", async () => {
    renderAt("/manettes");
    expect(await screen.findByText(/les boutons de la console ne contrôlent pas le jeu/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Utiliser les boutons de la console/ }));
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/players", players: [0, 1, 2, 3] }));
    expect(await screen.findByRole("heading", { name: "Bibliothèque", level: 1 })).toBeInTheDocument();
  });

  it("joueur 1 sur une manette branchée, sans jeu en cours : propose de choisir un jeu", async () => {
    renderAt("/manettes");
    // La 8BitDo du joueur 2 est grisée pour le joueur 1 ; le joueur 2 prend le numéro libre du joueur 1, qui
    // reçoit la 8BitDo.
    const p1 = await screen.findByLabelText("Joueur 1");
    expect(within(p1).getByRole("option", { name: "8BitDo Pro 2 · manette n°1 — joueur 2" })).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText("Joueur 2"), "2");
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/players", players: [1, 2, 0, 3] }));
    expect(screen.queryByRole("button", { name: /boutons de la console/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Choisir un jeu/ }));
    expect(await screen.findByRole("heading", { name: "Bibliothèque", level: 1 })).toBeInTheDocument();
  });

  it("donne au joueur 1 une manette connectée à l'ordinateur, relayée vers la console", async () => {
    const sent: string[] = [];
    vi.stubGlobal("WebSocket", class {
      static OPEN = 1;
      readyState = 0;
      onmessage: ((e: { data: string }) => void) | null = null;
      onclose: (() => void) | null = null;
      constructor(url: string) {
        relayToken = new URL(url).searchParams.get("token")!;
        setTimeout(() => { this.readyState = 1; this.onmessage?.({ data: '{"ready": true}' }); }, 0);
      }
      send(data: string) { sent.push(data); }
      close() { this.readyState = 3; }
    });
    const pad = { index: 0, id: "Xbox Wireless Controller (STANDARD GAMEPAD Vendor: 045e Product: 0b13)", connected: true,
                  mapping: "standard", buttons: [{ value: 1, pressed: true }], axes: [0, 0, 0, 0] };
    Object.defineProperty(navigator, "getGamepads", { value: () => [pad], configurable: true });
    Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => setTimeout(() => cb(0), 0));

    renderAt("/manettes");
    await userEvent.selectOptions(await screen.findByLabelText("Joueur 1"), "Manette de l'ordinateur · Xbox Wireless Controller");
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/players", players: [4, 1, 0, 3] }), { timeout: 3000 });
    expect(relayToken).toMatch(/^[a-z0-9]{4,16}$/);
    await waitFor(() => expect(JSON.parse(sent[0]!)).toEqual({ b: [1], a: [0, 0, 0, 0] }));
    expect(screen.getByLabelText("Joueur 1")).toHaveDisplayValue("Manette de l'ordinateur · Xbox Wireless Controller");

    // Les boutons de la console sont au joueur 3 : grisés pour le joueur 1.
    expect(within(screen.getByLabelText("Joueur 1")).getByRole("option", { name: "Boutons de la console — joueur 3" })).toBeDisabled();
  });

  it("choisit ce qui dirige le joueur 1 : la croix seule, ou la croix et un stick", async () => {
    renderAt("/manettes");
    const [p1] = await screen.findAllByLabelText("Direction");
    expect(p1).toHaveValue("2");  // réglage d'origine de la console : stick droit
    await userEvent.selectOptions(p1!, "Croix + stick gauche");
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/players", directions: [1, 0, 0, 0] }));
    expect(screen.getAllByLabelText("Direction")[0]).toHaveValue("1");
  });

  it("pendant un jeu, relance le jeu pour appliquer la manette", async () => {
    playingId = 1;
    renderAt("/manettes");
    await userEvent.click(await screen.findByRole("button", { name: /Utiliser les boutons de la console et relancer le jeu/ }));
    await waitFor(() => expect(bodies.at(-1)).toMatchObject({ url: "/api/games/1/launch" }));
    expect(bodies.at(-2)).toEqual({ url: "/api/players", players: [0, 1, 2, 3] });

    await userEvent.selectOptions(screen.getByLabelText("Joueur 2"), "2");
    expect(await screen.findByText(/relance-le pour appliquer le changement/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Relancer le jeu pour appliquer/ }));
    await waitFor(() => expect(bodies.filter((b) => b.url === "/api/games/1/launch")).toHaveLength(2));
  });

  it("est une page à part, absente de la page Bluetooth", async () => {
    renderAt("/bluetooth");
    expect(await screen.findByRole("link", { name: /Manettes/ })).toBeInTheDocument();
    await screen.findByRole("region", { name: "Mes appareils" });
    expect(screen.queryByText("Qui contrôle le jeu ?")).not.toBeInTheDocument();
  });
});

describe("Bluetooth", () => {
  it("remonte l'appareil cliqué en tête de « Mes appareils »", async () => {
    renderAt("/bluetooth");
    const near = await screen.findByRole("region", { name: "Appareils à portée" });
    const tv = (await within(near).findByText("KD-43X8309C")).closest("li")!;
    await userEvent.click(within(tv).getByRole("button", { name: /Appairer et connecter/ }));
    const mine = screen.getByRole("region", { name: "Mes appareils" });
    expect(within(mine).getByText("KD-43X8309C")).toBeInTheDocument();
    expect(within(near).queryByText("KD-43X8309C")).not.toBeInTheDocument();
  });

  it("propose de relancer le jeu en cours quand la sortie du son change", async () => {
    playingId = 1;
    renderAt("/bluetooth");
    const speaker = (await screen.findByText("JBL Flip")).closest("li")!;
    await userEvent.click(within(speaker).getByRole("button", { name: /Envoyer le son des jeux sur cet appareil/ }));
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/bluetooth/audio-output", address: "F8:DF:15:00:00:02" }));
    expect(await screen.findByText(/Super Mario World était déjà lancé/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Relancer le jeu/ }));
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/games/1/launch", slot: "auto" }));
  });

  it("teste le son sur l'enceinte connectée", async () => {
    renderAt("/bluetooth");
    const speaker = (await screen.findByText("JBL Flip")).closest("li")!;
    await userEvent.click(within(speaker).getByRole("button", { name: /Tester le son/ }));
    await waitFor(() => expect(bodies.at(-1)).toEqual({ url: "/api/bluetooth/test-sound", address: "F8:DF:15:00:00:02" }));
    expect(await within(speaker).findByText(/Un carillon vient de sonner/)).toBeInTheDocument();
  });

  it("sans jeu en cours, ne parle pas de relancer", async () => {
    renderAt("/bluetooth");
    const speaker = (await screen.findByText("JBL Flip")).closest("li")!;
    await userEvent.click(within(speaker).getByRole("button", { name: /Envoyer le son des jeux sur cet appareil/ }));
    await waitFor(() => expect(bodies.at(-1)).toMatchObject({ url: "/api/bluetooth/audio-output" }));
    expect(screen.queryByText(/était déjà lancé/)).not.toBeInTheDocument();
  });
});

describe("Captures d'écran", () => {
  it("prend une capture du jeu en cours depuis le tableau de bord, puis mène à ses captures", async () => {
    playingId = 1;
    renderAt("/");
    await userEvent.click(await screen.findByRole("button", { name: /Capture d'écran/ }));
    const done = await screen.findByRole("link", { name: /Capture enregistrée/ });
    expect(calls).toContain("/api/device/screenshot");
    await userEvent.click(done);
    const game = await screen.findByRole("region", { name: /Super Mario World/ });
    expect(within(game).getAllByRole("img")).toHaveLength(3);
    expect(within(game).getByText("3 captures")).toBeInTheDocument();
  });

  it("prend une capture depuis le jeu en cours de la barre du haut, sur les autres pages", async () => {
    playingId = 1;
    renderAt("/bluetooth");
    const chip = await screen.findByRole("status", { name: "En cours sur la console" });
    await userEvent.click(await within(chip).findByRole("button", { name: /Capture d'écran/ }));
    expect(await within(chip).findByRole("link", { name: /Capture enregistrée/ })).toBeInTheDocument();
    expect(calls).toContain("/api/device/screenshot");
  });

  it("liste les captures par jeu et en supprime une", async () => {
    renderAt("/captures");
    const game = await screen.findByRole("region", { name: /Super Mario World/ });
    expect(within(game).getAllByRole("img")).toHaveLength(2);
    await userEvent.click(within(game).getAllByRole("button", { name: "Supprimer la capture" })[0]!);
    await waitFor(() => expect(within(game).getAllByRole("img")).toHaveLength(1));
    expect(within(game).getByText("1 capture")).toBeInTheDocument();
  });

  it("partage une capture sur X (image copiée, éditeur ouvert) puis sur Reddit (image téléchargée)", async () => {
    const opened: string[] = [];
    const open = vi.spyOn(window, "open").mockImplementation((u) => { opened.push(String(u)); return {} as Window; });
    const write = vi.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { write, writeText: vi.fn(async () => undefined) } });
    vi.stubGlobal("ClipboardItem", class { constructor(public items: unknown) {} });
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    renderAt("/captures");
    const game = await screen.findByRole("region", { name: /Super Mario World/ });
    await userEvent.click(within(game).getAllByRole("button", { name: "Partager sur les réseaux" })[0]!);
    const dialog = await screen.findByRole("dialog", { name: "Partager la capture" });
    const box = within(dialog).getByLabelText("Texte du message");
    expect(box).toHaveValue("");  // vide : on écrit, ou on fait générer par l'IA
    await userEvent.type(box, "Mon record #retrogaming");
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "X" })).toBeEnabled());
    await userEvent.click(within(dialog).getByRole("button", { name: "X" }));
    expect(await within(dialog).findByText(/Image copiée : colle-la/)).toBeInTheDocument();
    expect(write).toHaveBeenCalled();
    expect(opened.at(-1)).toBe("https://x.com/intent/post?text=" + encodeURIComponent("Mon record #retrogaming"));
    await userEvent.selectOptions(within(dialog).getByLabelText("Communauté Reddit"), "retrogaming");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reddit" }));
    expect(await within(dialog).findByText(/Image téléchargée : ajoute-la au post Reddit/)).toBeInTheDocument();
    expect(opened.at(-1)).toBe("https://www.reddit.com/r/retrogaming/submit?type=IMAGE&title=" + encodeURIComponent("Mon record"));
    open.mockRestore();
    vi.unstubAllGlobals();
  });

  it("l'IA écrit le texte du post à la demande, puis « Régénérer » (et au changement de ton)", async () => {
    llm = { provider: "local", model: "gemma", base_url: "http://localhost:1234/v1", key: false, tested: true };
    renderAt("/captures");
    const game = await screen.findByRole("region", { name: /Super Mario World/ });
    await userEvent.click(within(game).getAllByRole("button", { name: "Partager sur les réseaux" })[0]!);
    const dialog = await screen.findByRole("dialog", { name: "Partager la capture" });
    expect(within(dialog).getByLabelText("Texte du message")).toHaveValue("");
    expect(bodies.some((b) => String(b.url).endsWith("/caption"))).toBe(false);  // rien n'est écrit sans le demander
    await userEvent.click(await within(dialog).findByRole("button", { name: /Générer avec l'IA/ }));
    await waitFor(() => expect(within(dialog).getByLabelText("Texte du message")).toHaveValue("Brouillon 1 de l'IA\n#retrogaming"));
    expect(within(dialog).queryByText(/Proposé par/)).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /Générer avec l'IA/ })).not.toBeInTheDocument();
    const first = bodies.find((b) => String(b.url).endsWith("/caption"));
    expect(first).toMatchObject({ lang: "fr", tone: "nostalgic", previous: [] });
    await userEvent.selectOptions(within(dialog).getByLabelText("Ton du post"), "Défi");
    await waitFor(() => expect(within(dialog).getByLabelText("Texte du message")).toHaveValue("Brouillon 2 de l'IA\n#retrogaming"));
    expect(bodies.filter((b) => String(b.url).endsWith("/caption")).at(-1)).toMatchObject(
      { tone: "challenge", previous: ["Brouillon 1 de l'IA\n#retrogaming"] });
    await userEvent.click(within(dialog).getByRole("button", { name: /Régénérer/ }));
    await waitFor(() => expect(within(dialog).getByLabelText("Texte du message")).toHaveValue("Brouillon 3 de l'IA\n#retrogaming"));
  });

  it("sans capture, explique comment en prendre ; la section est dans le menu", async () => {
    shots = [];
    renderAt("/captures");
    expect(await screen.findByText("Pas encore de capture")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Captures" })).toBeInTheDocument();
  });

  it("la fiche du jeu montre ses captures", async () => {
    renderAt("/bibliotheque?all=1");
    await userEvent.click(await screen.findByText("Super Mario World"));
    const section = await within(await screen.findByRole("dialog")).findByRole("region", { name: "Mes captures" });
    expect(within(section).getAllByRole("img")).toHaveLength(2);
  });
});

describe("Tableau de bord", () => {
  it("masque ce que le système de la console ne sait pas faire", async () => {
    systemCaps = { launch: false, resume_slot: false, quit: true, save_state: true, now_playing: true, saves: true,
      retroarch_logs: false, bluetooth: false, bluetooth_audio: false, players: false, volume: false, on_screen_message: true };
    renderAt("/");
    expect(await screen.findByText("muOS")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Bluetooth" })).not.toBeInTheDocument();
    const played = await screen.findByRole("region", { name: "Joués récemment" });
    expect(await within(played).findByText("Super Mario World")).toBeInTheDocument();
    expect(within(played).queryByRole("button", { name: /Rejouer/ })).not.toBeInTheDocument();
  });

  it("propose le genre et la console qui correspondent à la recherche", async () => {
    renderAt("/");
    const box = await screen.findByRole("combobox", { name: "Rechercher un jeu" });
    await userEvent.type(box, "sport");
    expect(await screen.findByRole("option", { name: /Sport.*Genre · 1 jeu/ })).toBeInTheDocument();
    await userEvent.clear(box);
    await userEvent.type(box, "super");
    expect(await screen.findByRole("option", { name: /Super Nintendo.*Console · 2 jeux/ })).toBeInTheDocument();
    await userEvent.clear(box);
    await userEvent.type(box, "sport");
    await userEvent.click(await screen.findByRole("option", { name: /Sport.*Genre/ }));
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("?genre=sport&all=1"));
  });

  it("recherche dès le tableau de bord et ouvre les résultats dans la bibliothèque", async () => {
    renderAt("/");
    const box = await screen.findByRole("combobox", { name: "Rechercher un jeu" });
    await userEvent.type(box, "maro");
    expect(await screen.findByRole("option", { name: /Super Mario World/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Genre/ })).not.toBeInTheDocument();
    expect(calls.some((c) => c.startsWith("/api/search?q=maro"))).toBe(true);
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("?q=maro&all=1"));
  });

  it("garde les dernières recherches et les propose quand le champ est vide", async () => {
    renderAt("/");
    const box = await screen.findByRole("combobox", { name: "Rechercher un jeu" });
    await userEvent.type(box, "maro");
    await screen.findByRole("option", { name: /Super Mario World/ });
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("?q=maro&all=1"));

    await userEvent.clear(box);
    await userEvent.click(box);
    const recent = await screen.findByRole("listbox", { name: "Recherches récentes" });
    await userEvent.click(within(recent).getByRole("option", { name: /maro/ }));
    expect(box).toHaveValue("maro");

    await userEvent.clear(box);
    await userEvent.click(screen.getByRole("button", { name: "Retirer « maro » des recherches récentes" }));
    expect(screen.queryByRole("listbox", { name: "Recherches récentes" })).not.toBeInTheDocument();
    expect(localStorage.getItem("agm-recent-searches")).toBeNull();
  });

  it("montre d'abord les jeux joués récemment et permet de les relancer", async () => {
    renderAt("/");
    const played = await screen.findByRole("region", { name: "Joués récemment" });
    expect(await within(played).findByText("Super Mario World")).toBeInTheDocument();
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings.indexOf("Joués récemment")).toBeLessThan(headings.indexOf("Derniers ajouts"));
    expect(headings.indexOf("Derniers ajouts")).toBeLessThan(headings.indexOf("Carte microSD"));
    const added = screen.getByRole("region", { name: "Derniers ajouts" });
    expect(within(added).getByRole("link", { name: /Ajouter des jeux/ })).toHaveAttribute("href", "/ajouter-des-jeux");
    await userEvent.click(within(played).getByRole("button", { name: "Rejouer à Super Mario World sur la console" }));
    await waitFor(() => expect(calls.some((c) => c === "/api/games/1/launch")).toBe(true));
  });

  it("résume le catalogue et signale une console hors ligne", async () => {
    deviceOnline = false;
    renderAt("/");
    expect(await screen.findByRole("heading", { level: 1, name: "2 jeux sur 1 console" })).toBeInTheDocument();
    expect(await screen.findByText(/hors ligne\. Le catalogue reste consultable/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Synchroniser/ })).toBeDisabled();
    expect(screen.getByText("Console injoignable sur 192.168.86.242:22")).toBeInTheDocument();
  });
});

describe("Transferts", () => {
  it("propose la console, signale le fichier déjà présent et ne le remplace pas par défaut", async () => {
    renderAt("/ajouter-des-jeux");
    expect(await screen.findByText("Zelda (Europe).sfc")).toBeInTheDocument();
    expect(await screen.findByText(/Déjà sur la carte, taille différente/)).toBeInTheDocument();
    expect(screen.getByText(/1 fichier déjà présent ne sera pas copié/)).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: "Copier sur la console" });
    await waitFor(() => expect(btn).toBeEnabled());
    await userEvent.setup({ pointerEventsCheck: 0 }).click(btn);
    await waitFor(() => expect(bodies.some((b) => b.url === "/api/transfers")).toBe(true));
    const sent = bodies.find((b) => b.url === "/api/transfers") as { items: { on_conflict: string; platform: string }[]; confirm_overwrite: boolean };
    expect(sent.confirm_overwrite).toBe(false);
    expect(sent.items.map((i) => [i.platform, i.on_conflict])).toEqual([["SFC", "skip"], ["SFC", "skip"]]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
