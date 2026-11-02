/**
 * Moteur de la démo : remplace le serveur local du Manager dans le navigateur (romkade.com/demo). Toutes les requêtes
 * /api, ROMKADE Cloud et Supabase sont servies ici, sans réseau, sur une console simulée : jeu en cours, volume,
 * sauvegardes, captures, temps de jeu, transferts. L'état vit en mémoire : recharger la page remet la démo à zéro.
 */
import type { components } from "../api/schema";
import { getLang } from "../i18n/core";
import { coverUrl, screenUrl } from "./art";
import { CONSOLE, FAVORITES, GAMES, PLATFORMS, RECENT, WITH_SAVES, type DemoGame } from "./data";
import SYSTEMS from "./systems.json";

type S = components["schemas"];
type GameOut = S["GameOut"];
type Json = unknown;

const ROMS = "/mnt/mmc/Roms";
const SYSTEM = "anbernic-stock-mod";
const DAY = 86_400_000;
const now = () => Date.now();
const iso = (ms: number) => new Date(ms).toISOString();
const START = now();

const GENRE_LABELS: Record<string, string> = {
  action: "Action", aventure: "Aventure", beat: "Beat'em up", combat: "Combat", course: "Course", plateforme: "Plateforme",
  rpg: "Jeu de rôle", shmup: "Shoot'em up", tir: "Tir", reflexion: "Réflexion", strategie: "Stratégie",
  simulation: "Simulation", flipper: "Flipper",
};

/** Ce que la démo ne fait pas (réglages du compte, téléchargements…), dans la langue de l'interface. */
const UNAVAILABLE = {
  fr: "Pas disponible dans la démo : installez ROMKADE Manager pour l'utiliser avec votre console.",
  en: "Not available in the demo: install ROMKADE Manager to use it with your console.",
  es: "No disponible en la demo: instala ROMKADE Manager para usarlo con tu consola.",
};
const NO_AI = {
  fr: "L'assistant utilise l'IA que vous choisissez (Claude, ChatGPT, Gemini ou une IA locale) : il n'est pas branché dans la démo.",
  en: "The assistant uses the AI you choose (Claude, ChatGPT, Gemini or a local AI): it is not connected in the demo.",
  es: "El asistente usa la IA que elijas (Claude, ChatGPT, Gemini o una IA local): no está conectado en la demo.",
};
const unavailable = () => UNAVAILABLE[getLang()];

class DemoError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

// ---------------------------------------------------------------------------------------------------------------
// Bibliothèque

type Entry = { id: number; game: DemoGame; added: number; favorite: boolean; broken: boolean; disliked: boolean; liked: boolean };

const platformOf = (dir: string) => PLATFORMS.find((p) => p.directory === dir)!;
const filenameOf = (g: DemoGame) => `${g.title} (${g.region}).${platformOf(g.dir).ext}`;

const library: Entry[] = GAMES.map((game, i) => ({
  id: i + 1, game, added: START - (i * 2.3 + 1) * DAY, favorite: FAVORITES.includes(i), broken: false, disliked: false, liked: false,
}));

function gameOut(e: Entry): GameOut {
  const g = e.game, p = platformOf(g.dir), filename = filenameOf(g);
  return {
    id: e.id, platform: { id: p.id, directory: p.directory, code: p.code, label: p.label },
    title: g.title, full_title: null, normalized_title: g.title.toLowerCase(), filename, relative_path: filename,
    extension: p.ext, region: g.region, size: g.size, modified_at: iso(e.added), role: "candidate",
    has_image: true, image_url: coverUrl(g.title, g.scene, p.label), boxart_url: null, metadata_status: "matched",
    genre: g.genre, genre_label: GENRE_LABELS[g.genre] ?? null, genre_detail: null, subgenre: null, subgenre_label: null,
    release_year: g.year, developer: g.dev, publisher: g.dev, players: g.players, players_link: g.dir === "GB" && g.players > 1,
    first_seen_at: iso(e.added), last_seen_at: iso(START), present: true, youtube_url: null,
  };
}

const entry = (id: number) => {
  const e = library.find((x) => x.id === id);
  if (!e) throw new DemoError(404, "game_not_found", "Jeu introuvable.");
  return e;
};
const romPath = (e: Entry) => `${ROMS}/${e.game.dir}/${filenameOf(e.game)}`;

function gameDetail(e: Entry): S["GameDetailOut"] {
  const t = e.game.text;
  return {
    ...gameOut(e), release_date: `${e.game.year}-06-01`, franchise: null, description: t.en,
    descriptions: { fr: { text: t.fr, origin: "source" }, en: { text: t.en, origin: "source" }, es: { text: t.es, origin: "source" } },
    favorite: e.favorite, broken: e.broken, disliked: e.disliked, liked: e.liked, info_url: null,
    remote_path: romPath(e), image_relpath: null, possible_duplicates: [], history: [],
  };
}

function filterGames(q: URLSearchParams): Entry[] {
  const text = (q.get("q") ?? "").trim().toLowerCase();
  const list = (k: string) => q.getAll(k);
  const [platforms, genres, regions, exts] = [list("platform"), list("genre"), list("region"), list("extension")];
  const players = q.get("players");
  let out = library.filter((e) => {
    const g = e.game;
    if (text && !`${g.title} ${g.dev}`.toLowerCase().includes(text)) return false;
    if (platforms.length && !platforms.includes(g.dir)) return false;
    if (genres.length && !genres.includes(g.genre)) return false;
    if (regions.length && !regions.includes(g.region)) return false;
    if (exts.length && !exts.includes(platformOf(g.dir).ext)) return false;
    if (q.get("favorite") === "true" && !e.favorite) return false;
    if (q.get("broken") === "true" && !e.broken) return false;
    if (players === "solo" && g.players !== 1) return false;
    if ((players === "2" || players === "4") && g.players < Number(players)) return false;
    if (players === "link" && !(g.dir === "GB" && g.players > 1)) return false;
    return true;
  });
  const sort = q.get("sort") ?? "name";
  const key = (e: Entry): number | string =>
    sort === "size" ? e.game.size : sort === "year" ? e.game.year : sort === "date" || sort === "added" ? e.added : e.game.title;
  out = [...out].sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0));
  if (q.get("order") === "desc") out.reverse();
  return out;
}

function gamesPage(q: URLSearchParams): S["GamesPageOut"] {
  const all = filterGames(q);
  const offset = Number(q.get("offset") ?? 0), limit = Number(q.get("limit") ?? 60);
  return { page: { total: all.length, offset, limit }, items: all.slice(offset, offset + limit).map(gameOut) };
}

function facets(q: URLSearchParams): S["FacetsOut"] {
  const platforms = q.getAll("platform");
  const games = library.filter((e) => !platforms.length || platforms.includes(e.game.dir));
  const count = (key: (e: Entry) => string, label?: (v: string) => string) => {
    const m = new Map<string, number>();
    games.forEach((e) => m.set(key(e), (m.get(key(e)) ?? 0) + 1));
    return [...m].sort((a, b) => b[1] - a[1]).map(([value, n]) => ({ value, count: n, label: label?.(value) ?? null }));
  };
  return {
    extensions: count((e) => platformOf(e.game.dir).ext), regions: count((e) => e.game.region),
    genres: count((e) => e.game.genre, (v) => GENRE_LABELS[v] ?? v), subgenres: [],
  };
}

function platformsOut(): S["CatalogPlatformOut"][] {
  return PLATFORMS.map((p) => {
    const games = library.filter((e) => e.game.dir === p.directory);
    const bytes = games.reduce((s, e) => s + e.game.size, 0);
    return {
      id: p.id, directory: p.directory, code: p.code, label: p.label, label_status: "confirmed", kind: p.kind, present: true,
      image_dir_present: true, last_scanned_at: iso(lastSync.finished), game_count: games.length, file_count: games.length,
      total_bytes: bytes, image_count: games.length, images_matched: games.length,
    };
  }).filter((p) => p.game_count > 0);
}

// ---------------------------------------------------------------------------------------------------------------
// Synchronisation

const STORAGE_TOTAL = 64 * 1024 ** 3;
const lastSync = { id: 3, started: START - 2 * 3_600_000, finished: START - 2 * 3_600_000 + 9000 };
const runs: S["ScanRunOut"][] = [1, 2, 3].map((id) => ({
  id, status: "completed", trigger: "manual", started_at: iso(START - (3 - id) * 3 * DAY - 2 * 3_600_000),
  finished_at: iso(START - (3 - id) * 3 * DAY - 2 * 3_600_000 + 9000), platforms_total: PLATFORMS.length,
  platforms_done: PLATFORMS.length, files_seen: library.length, added: id === 1 ? library.length : 2, modified: 0, removed: 0,
  restored: 0, images_seen: library.length, images_matched: library.length, error: null, platform_errors: {},
}));

function startSync(): S["ScanRunOut"] {
  const run: S["ScanRunOut"] = { ...runs[runs.length - 1]!, id: runs.length + 1, status: "running", started_at: iso(now()),
    finished_at: null, platforms_done: 0, added: 0, files_seen: 0 };
  runs.push(run);
  const tick = setInterval(() => {
    run.platforms_done += 1;
    run.files_seen = library.filter((e) => PLATFORMS.slice(0, run.platforms_done).some((p) => p.directory === e.game.dir)).length;
    if (run.platforms_done >= run.platforms_total) {
      clearInterval(tick);
      Object.assign(run, { status: "completed", finished_at: iso(now()), files_seen: library.length });
      Object.assign(lastSync, { id: run.id, started: Date.parse(run.started_at), finished: now() });
    }
  }, 500);
  return run;
}

function status(): S["CatalogStatusOut"] {
  const bytes = library.reduce((s, e) => s + e.game.size, 0);
  const run = runs[runs.length - 1]!;
  return {
    synced: true, sync_running: run.status === "running", last_run: run, last_successful_sync_at: iso(lastSync.finished),
    platform_count: platformsOut().length, game_count: library.length, file_count: library.length, total_bytes: bytes,
    storage_total_bytes: STORAGE_TOTAL, storage_free_bytes: STORAGE_TOTAL - bytes - 6 * 1024 ** 3, storage_measured_at: iso(lastSync.finished),
  };
}

// ---------------------------------------------------------------------------------------------------------------
// Console : jeu en cours, volume, sauvegardes, captures, temps de jeu

const consoleState = { playing: null as { id: number; since: number } | null, volume: 60, muted: false };
const playSettings: S["PlaySettings"] = { alert_enabled: false, alert_minutes: 60, alert_scope: "session", repeat_minutes: 15, console_message: true };

const startOfDay = (ms: number) => { const d = new Date(ms); d.setHours(0, 0, 0, 0); return d.getTime(); };

type Session = { id: number; gameId: number; start: number; seconds: number };
const sessions: Session[] = [];
{
  let id = 1;
  for (let d = 13; d >= 0; d--) {
    const count = d % 3 === 0 ? 2 : d % 4 === 1 ? 0 : 1;
    for (let k = 0; k < count; k++) {
      const gameId = library[RECENT[(d + k) % RECENT.length]!]!.id;
      const seconds = 600 + ((d * 7 + k * 13) % 9) * 420;
      const day = new Date(START);
      day.setDate(day.getDate() - d);
      day.setHours(18 + k * 2, (d * 17) % 60, 0, 0);  // en soirée ; aujourd'hui, avant l'ouverture de la démo
      const start = Math.min(day.getTime(), START - (k + 1) * 2 * 3_600_000 - seconds * 1000);
      sessions.push({ id: id++, gameId, start, seconds });
    }
  }
}
const sessionOut = (s: Session): S["SessionOut"] => {
  const e = entry(s.gameId);
  return { id: s.id, title: e.game.title, platform: e.game.dir, game: gameOut(e), started_at: iso(s.start),
    ended_at: iso(s.start + s.seconds * 1000), seconds: s.seconds };
};
const liveSeconds = () => (consoleState.playing ? Math.round((now() - consoleState.playing.since) / 1000) : 0);

function quitGame() {
  const p = consoleState.playing;
  if (p) sessions.push({ id: sessions.length + 1, gameId: p.id, start: p.since, seconds: Math.max(1, liveSeconds()) });
  consoleState.playing = null;
}

function playStats(q: URLSearchParams): S["PlayStatsOut"] {
  const days = Number(q.get("days") ?? 14);
  const first = new Date(startOfDay(now()));
  first.setDate(first.getDate() - (days - 1));
  const start = q.get("start") ? Date.parse(q.get("start")!) : first.getTime();
  const end = q.get("end") ? Date.parse(q.get("end")!) + DAY : now() + 1;
  const inRange = sessions.filter((s) => s.start >= start && s.start < end);
  const today = startOfDay(now());
  const sum = (list: Session[]) => list.reduce((n, s) => n + s.seconds, 0);
  const dayList: S["DayOut"][] = [];
  for (const d = new Date(startOfDay(start)); d.getTime() < end; d.setDate(d.getDate() + 1)) {  // jours civils (heure d'été)
    const t = d.getTime();
    const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    dayList.push({ date, seconds: sum(inRange.filter((s) => startOfDay(s.start) === t)) + (t === today ? liveSeconds() : 0) });
  }
  const byGame = new Map<number, Session[]>();
  inRange.forEach((s) => byGame.set(s.gameId, [...(byGame.get(s.gameId) ?? []), s]));
  const games: S["GameTimeOut"][] = [...byGame].map(([id, list]) => {
    const e = entry(id);
    return { key: romPath(e), ra_seconds: 0, title: e.game.title, platform: e.game.dir, game: gameOut(e), seconds: sum(list),
      sessions: list.length, last_played: iso(Math.max(...list.map((s) => s.start + s.seconds * 1000))), last_played_console: null };
  }).sort((a, b) => b.seconds - a.seconds);
  return {
    today_seconds: sum(sessions.filter((s) => s.start >= today)) + liveSeconds(),
    week_seconds: sum(sessions.filter((s) => s.start >= today - 6 * DAY)) + liveSeconds(), total_seconds: sum(sessions) + liveSeconds(),
    period: q.get("start") ? { start: q.get("start")!, end: q.get("end")! } : null, days: dayList, games,
    sessions: [...inRange].reverse().map(sessionOut), retroarch_available: true,
  };
}

function recentPlayed(limit: number): S["RecentGameOut"][] {
  const seen = new Map<number, Session[]>();
  [...sessions].reverse().forEach((s) => seen.set(s.gameId, [...(seen.get(s.gameId) ?? []), s]));
  return [...seen].slice(0, limit).map(([id, list]) => {
    const e = entry(id);
    return { title: e.game.title, platform: e.game.dir, rom_path: romPath(e), game: gameOut(e),
      last_played: iso(list[0]!.start + list[0]!.seconds * 1000), seconds: list.reduce((n, s) => n + s.seconds, 0) };
  });
}

function nowPlaying(): S["NowPlayingOut"] {
  const p = consoleState.playing;
  if (!p) return { playing: false, process: null, rom_path: null, menu: true, game: null };
  const e = entry(p.id);
  return { playing: true, process: "retroarch", rom_path: romPath(e), menu: false, game: gameOut(e) };
}

function playState(): S["PlayStateOut"] {
  const p = consoleState.playing;
  const e = p ? entry(p.id) : null;
  return { playing: !!p, game: e ? gameOut(e) : null, title: e?.game.title ?? null, session_started_at: p ? iso(p.since) : null,
    session_seconds: liveSeconds(), today_seconds: playStats(new URLSearchParams("days=1")).today_seconds, settings: playSettings, alerts: [] };
}

const volumeOut = (): S["VolumeOut"] => ({ mode: "amixer", adjustable: true, percent: consoleState.volume, muted: consoleState.muted,
  game_running: !!consoleState.playing });

type SaveOut = S["app__catalog_schemas__SaveOut"];
let saves: SaveOut[] = [];
function addSave(e: Entry, kind: "sram" | "state", slot: string | null, at: number) {
  const base = filenameOf(e.game).replace(/\.[^.]+$/, "");
  const name = kind === "sram" ? `${base}.srm` : `${base}.state${slot === "0" ? "" : slot}`;
  const rel = `${kind === "sram" ? "saves_RA" : "states_RA"}/Roms/${e.game.dir}/${name}`;
  saves = saves.filter((s) => s.rel !== rel);
  saves.push({ path: `/mnt/mmc/${rel}`, rel, source: "retroarch", kind, slot, platform: e.game.dir, name,
    size: kind === "sram" ? 8192 : 180_000 + (e.id % 7) * 20_000, modified_at: iso(at), game: gameOut(e) });
}
WITH_SAVES.forEach((i, k) => {
  const e = library[i]!;
  addSave(e, "sram", null, START - (k + 1) * DAY);
  if (k % 2 === 0) addSave(e, "state", "0", START - (k + 1) * DAY + 3_600_000);
});
const backups: S["BackupOut"][] = [{
  id: "20261031-2100", created_at: iso(START - DAY), auto: true, bytes: saves.reduce((n, s) => n + (s.size ?? 0), 0),
  files: saves.map((s) => ({ rel: s.rel, size: s.size ?? 0, kind: s.kind, slot: s.slot, platform: s.platform, game_title: s.game?.title ?? null, modified_at: s.modified_at })),
}];

const shots = new Map<number, S["ShotOut"][]>();
function addShot(e: Entry, at: number): S["ShotOut"] {
  const list = shots.get(e.id) ?? [];
  const shot = { name: `${e.game.title.replace(/\W+/g, "-")}-${list.length + 1}.png`, taken_at: iso(at), size: 96_000,
    url: screenUrl(e.game.title, e.game.scene, e.id * 3 + list.length) };
  shots.set(e.id, [shot, ...list]);
  return shot;
}
[0, 3, 5].forEach((i, k) => { addShot(library[i]!, START - (k + 2) * DAY); addShot(library[i]!, START - (k + 1) * DAY); });

// ---------------------------------------------------------------------------------------------------------------
// Ajouter des jeux : envoi, plan, transfert simulé, puis le jeu entre dans la bibliothèque

const EXT_TO_DIR: Record<string, string> = Object.fromEntries(PLATFORMS.map((p) => [p.ext, p.directory]));
Object.assign(EXT_TO_DIR, { smc: "SFC", gbc: "GB", gen: "MD", bin: "MD", cue: "PS", iso: "PS", pbp: "PS" });
const uploads: S["UploadOut"][] = [];
const transfers: S["TransferOut"][] = [];
const transferListeners = new Set<(data: string) => void>();
const emitTransfers = () => {
  const data = JSON.stringify({ active: transfers.filter((t) => ["queued", "running", "verifying"].includes(t.status)),
    finished: transfers.filter((t) => t.status === "completed").length });
  transferListeners.forEach((fn) => fn(data));
};

function plan(items: { upload_id: string; platform?: string | null }[]): S["PlanOut"] {
  const out = items.map((it): S["PlanItemOut"] => {
    const u = uploads.find((x) => x.id === it.upload_id)!;
    const ext = u.filename.split(".").pop()!.toLowerCase();
    const dir = it.platform ?? EXT_TO_DIR[ext] ?? null;
    return { upload_id: u.id, filename: u.filename, size: u.size, platform: dir, platform_label: dir ? platformOf(dir).label : null,
      platform_choices: dir ? [dir] : PLATFORMS.map((p) => p.directory), conflict: null, warnings: [], error: null };
  });
  const total = out.reduce((n, i) => n + i.size, 0);
  return { items: out, total_bytes: total, free_bytes: status().storage_free_bytes, margin_bytes: 256 * 1024 ** 2, fits: true,
    ready: out.every((i) => i.platform) };
}

function startTransfers(items: S["StartItem"][]): S["TransferOut"][] {
  const batch = `demo-${now()}`;
  const created = items.map((it): S["TransferOut"] => {
    const u = uploads.find((x) => x.id === it.upload_id)!;
    return { id: transfers.length + 1 + Math.random(), batch_id: batch, upload_id: u.id, filename: u.filename, final_filename: u.filename,
      platform_dir: it.platform, size: u.size, on_conflict: it.on_conflict, status: "queued", bytes_done: 0, speed_bps: null,
      eta_seconds: null, verify_method: null, remote_path: `${ROMS}/${it.platform}/${u.filename}`, backup_path: null, error: null,
      created_at: iso(now()), started_at: null, finished_at: null, retryable: false };
  });
  created.forEach((t, i) => { t.id = transfers.length + 1 + i; });
  transfers.unshift(...created);
  const step = () => {
    const t = transfers.find((x) => x.status === "queued" || x.status === "running" || x.status === "verifying");
    if (!t) return;
    const speed = 4 * 1024 ** 2;
    if (t.status === "queued") Object.assign(t, { status: "running", started_at: iso(now()) });
    else if (t.status === "running") {
      t.bytes_done = Math.min(t.size, t.bytes_done + Math.max(speed / 2, t.size / 6));
      Object.assign(t, { speed_bps: speed, eta_seconds: Math.ceil((t.size - t.bytes_done) / speed) });
      if (t.bytes_done >= t.size) Object.assign(t, { status: "verifying", verify_method: "sha256" });
    } else {
      Object.assign(t, { status: "completed", finished_at: iso(now()), speed_bps: null, eta_seconds: 0 });
      const u = uploads.findIndex((x) => x.id === t.upload_id);
      if (u >= 0) uploads.splice(u, 1);
      const title = t.filename.replace(/\.[^.]+$/, "").replace(/\s*\(.*?\)\s*/g, " ").trim() || t.filename;
      library.push({ id: library.length + 1, added: now(), favorite: false, broken: false, disliked: false, liked: false,
        game: { title, dir: t.platform_dir, genre: "action", year: 2026, dev: "—", players: 1, scene: "isles", region: "World", size: t.size,
          text: { fr: "Jeu ajouté pendant la démo.", en: "Game added during the demo.", es: "Juego añadido durante la demo." } } });
    }
    emitTransfers();
    setTimeout(step, 500);
  };
  setTimeout(step, 300);
  return created;
}

// ---------------------------------------------------------------------------------------------------------------
// Manettes, Bluetooth, son

const bt: S["BtStatusOut"] = {
  adapter: { present: true, powered: true, discovering: false, name: CONSOLE.name }, bluealsa: true, audio_output: null,
  devices: [
    { address: "A4:C1:38:12:6E:01", name: "Wireless Gamepad", icon: "input-gaming", kind: "gamepad", paired: true, trusted: true, connected: true, rssi: -48 },
    { address: "F0:13:C3:5A:22:9B", name: "BT Headphones", icon: "audio-headphones", kind: "audio", paired: true, trusted: true, connected: false, rssi: null },
  ],
};
const btDevice = (address: string) => bt.devices.find((d) => d.address === address);
let sound: S["SoundOut"] = { output: "speakers", address: null, hdmi: false, devices: bt.devices };
let players: S["PlayersOut"] = {
  controllers: [{ index: 0, name: "Manette intégrée", builtin: true, usb_id: null, remote: null },
    { index: 1, name: "Wireless Gamepad", builtin: false, usb_id: null, remote: null }],
  players: [0, 1], directions: [null, null], applied: true, game_running: false,
};

// ---------------------------------------------------------------------------------------------------------------
// Fiches : commandes, codes de triche

const CONTROLS: Record<string, [S["ControlOut"]["button"], string, string, string][]> = {
  default: [["dpad", "Se déplacer", "Move", "Moverse"], ["a", "Sauter / valider", "Jump / confirm", "Saltar / aceptar"],
    ["b", "Action / annuler", "Action / cancel", "Acción / cancelar"], ["start", "Pause", "Pause", "Pausa"]],
  course: [["dpad", "Diriger", "Steer", "Girar"], ["a", "Accélérer", "Accelerate", "Acelerar"], ["b", "Freiner", "Brake", "Frenar"],
    ["r1", "Turbo", "Boost", "Turbo"], ["start", "Pause", "Pause", "Pausa"]],
  rpg: [["dpad", "Se déplacer", "Move", "Moverse"], ["a", "Parler / valider", "Talk / confirm", "Hablar / aceptar"],
    ["b", "Annuler / courir", "Cancel / run", "Cancelar / correr"], ["x", "Menu", "Menu", "Menú"], ["start", "Carte", "Map", "Mapa"]],
  shmup: [["dpad", "Piloter", "Fly", "Pilotar"], ["a", "Tirer", "Fire", "Disparar"], ["b", "Bombe", "Bomb", "Bomba"], ["start", "Pause", "Pause", "Pausa"]],
};
function controls(e: Entry): S["GameControlsOut"] {
  const list = CONTROLS[e.game.genre] ?? CONTROLS.default!;
  return { status: "found", origin: "sourced", sources: [{ source: "ROMKADE", page: e.game.title, url: "https://romkade.com/" }],
    controls: list.map(([button, fr, en, es]) => ({ button, fr, en, es })), notes: null, updated_at: iso(START - 5 * DAY), can_generate: false };
}

function cheats(e: Entry): S["GameCheatsOut"] {
  const code = (n: number) => (e.id * 7919 + n * 104729).toString(16).toUpperCase().padStart(8, "0").slice(0, 8);
  return {
    available: true, can_install: true, license: "CC BY-SA 4.0", source_url: "https://romkade.com/",
    files: [{ name: `${e.game.title}.cht`, label: e.game.title, system: platformOf(e.game.dir).label, count: 4, cheats: [
      { desc: "Vies infinies", code: `${code(1).slice(0, 4)}-${code(1).slice(4)}` },
      { desc: "Énergie au maximum", code: `${code(2).slice(0, 4)}-${code(2).slice(4)}` },
      { desc: "Tous les niveaux ouverts", code: `${code(3).slice(0, 4)}-${code(3).slice(4)}` },
      { desc: "Saut plus haut", code: `${code(4).slice(0, 4)}-${code(4).slice(4)}` },
    ] }],
  };
}

// ---------------------------------------------------------------------------------------------------------------
// Routes

type Req = { method: string; path: string; q: URLSearchParams; body: Json };
type Handler = (r: Req, id: string) => Json | Promise<Json>;  // id : le paramètre {…} de l'adresse
const routes: [string, RegExp, Handler][] = [];
const on = (method: string, pattern: string, h: Handler) =>
  routes.push([method, new RegExp(`^${pattern.replace(/\{(\w+)\}/g, "([^/]+)")}$`), h]);
const ok = () => undefined;
const body = <T>(r: Req) => (r.body ?? {}) as T;
const sys = () => (SYSTEMS as unknown as S["SystemProfileOut"][]).find((s) => s.id === SYSTEM)!;
const settings = { host: CONSOLE.host, port: 22, username: "root", auth_method: "password" as const, key_path: null, roms_root: ROMS,
  connect_timeout: 10, system: SYSTEM };

// Catalogue
on("GET", "/catalog/status", status);
on("GET", "/platforms", platformsOut);
on("GET", "/games", (r) => gamesPage(r.q));
on("GET", "/games/{id}", (_r, id) => gameDetail(entry(+id)));
on("GET", "/favorites", (r) => library.filter((e) => e.favorite).slice(0, Number(r.q.get("limit") ?? 100)).map(gameOut));
for (const flag of ["favorite", "broken", "dislike", "like"] as const) {
  const field = ({ favorite: "favorite", broken: "broken", dislike: "disliked", like: "liked" } as const)[flag];
  on("PUT", `/games/{id}/${flag}`, (_r, id) => { const e = entry(+id); e[field] = true; if (flag === "favorite") e.disliked = false; if (flag === "dislike") e.favorite = false; });
  on("DELETE", `/games/{id}/${flag}`, (_r, id) => { entry(+id)[field] = false; });
}
on("GET", "/catalog/facets", (r) => facets(r.q));
on("POST", "/catalog/sync", startSync);
on("GET", "/catalog/sync/{id}", (_r, id) => runs.find((x) => x.id === +id));
on("GET", "/catalog/syncs", () => [...runs].reverse());
on("GET", "/catalog/changes", (r) => {
  const items = [...library].sort((a, b) => b.added - a.added).slice(0, 8).map((e): S["ChangeItemOut"] => ({
    scan_run_id: runs[runs.length - 1]!.id, change: "added", old_size: null, new_size: e.game.size, old_mtime: null,
    new_mtime: iso(e.added), run_started_at: iso(e.added), game: gameOut(e) }));
  return { page: { total: items.length, offset: 0, limit: Number(r.q.get("limit") ?? 50) }, items };
});
on("GET", "/catalog/duplicates", () => []);
on("GET", "/search", (r) => {
  const all = filterGames(r.q);
  return { items: all.slice(0, Number(r.q.get("limit") ?? 8)).map(gameOut), total: all.length, engine: "sqlite" };
});

// Console et réglages
on("GET", "/device/status", () => ({ connected: true, error: null }));
on("GET", "/settings", () => ({ ...settings, has_password: true, host_key_trusted: true }));
on("PUT", "/settings", (r) => { Object.assign(settings, body<object>(r)); return { ...settings, has_password: true, host_key_trusted: true }; });
on("PUT", "/settings/password", ok);
const hostKey = () => ({ host: settings.host, port: settings.port, algorithm: "ssh-ed25519", fingerprint: "SHA256:dEm0R0mKaDe+c0ns0le/S1mUl4t3d4Z9qWx2yPq8", trusted: true });
on("GET", "/device/host-key", hostKey);
on("POST", "/device/host-key/trust", hostKey);
on("POST", "/device/test-connection", () => ({ connected: true, host: settings.host, port: 22, username: "root", sftp: true, roms_root: ROMS,
  roms_root_exists: true, platform_dir_count: PLATFORMS.length, latency_ms: 18,
  storage: { path: ROMS, total_bytes: STORAGE_TOTAL, free_bytes: status().storage_free_bytes!, used_bytes: STORAGE_TOTAL - status().storage_free_bytes!,
    used_percent: Math.round((1 - status().storage_free_bytes! / STORAGE_TOTAL) * 100), method: "sftp_statvfs" } }));
on("POST", "/device/diagnose", () => ({ ok: true, host: settings.host, port: 22,
  steps: ["network", "ssh", "host_key", "auth", "command", "roms"].map((id, i) => ({ id, status: "ok", ms: 4 + i * 6, detail: null })) }));
on("POST", "/device/discover", () => ({ scanned: true, consoles: [{ host: CONSOLE.host, name: CONSOLE.name, banner: "SSH-2.0-dropbear", likely: true }] }));
on("GET", "/device/clock", () => ({ console_epoch: Math.round(now() / 1000), timezone: "Europe/Paris", utc_offset: "+01:00", mac_epoch: Math.round(now() / 1000), drift_seconds: 0 }));
on("POST", "/device/clock/sync", () => ({ console_epoch: Math.round(now() / 1000), timezone: "Europe/Paris", utc_offset: "+01:00", mac_epoch: Math.round(now() / 1000), drift_seconds: 0 }));
on("GET", "/systems", () => SYSTEMS);
const deviceSystem = () => ({ chosen: SYSTEM, profile: sys(), capabilities: sys().capabilities,
  detected: { profile: SYSTEM, label: sys().label, os_name: "Anbernic stock OS", roms_roots: [ROMS], suggested_roms_root: ROMS, es_http: false } });
on("GET", "/device/system", deviceSystem);
on("POST", "/device/system/detect", deviceSystem);

// Jouer
on("POST", "/games/{id}/launch", (_r, id) => {
  const e = entry(+id);
  quitGame();
  consoleState.playing = { id: e.id, since: now() };
  return { status: "launched", rom_path: romPath(e) };
});
on("GET", "/device/now-playing", nowPlaying);
on("GET", "/play/state", playState);
on("POST", "/device/quit-game", () => { quitGame(); return { result: "quit" }; });
on("POST", "/device/save-state", () => {
  const p = consoleState.playing;
  if (!p) throw new DemoError(409, "no_game_running", "Aucun jeu en cours sur la console.");
  addSave(entry(p.id), "state", "0", now());
  return { result: "saved" };
});
on("GET", "/volume", volumeOut);
on("PUT", "/volume", (r) => {
  const b = body<{ percent?: number; muted?: boolean }>(r);
  if (b.percent !== undefined) consoleState.volume = Math.max(0, Math.min(100, Math.round(b.percent)));
  if (b.muted !== undefined) consoleState.muted = b.muted;
  return volumeOut();
});
on("GET", "/play/recent", (r) => recentPlayed(Number(r.q.get("limit") ?? 12)));
on("GET", "/play/stats", (r) => playStats(r.q));
on("GET", "/play/settings", () => playSettings);
on("PUT", "/play/settings", (r) => Object.assign(playSettings, body<object>(r)));
on("POST", "/play/reset", ok);
on("POST", "/play/reset-all", ok);
on("POST", "/play/alerts/{id}/ack", ok);

// Sauvegardes et captures
on("GET", "/saves", () => ({ saves: [...saves].sort((a, b) => (b.modified_at ?? "").localeCompare(a.modified_at ?? "")), scanned_at: iso(now()) }));
on("GET", "/games/{id}/saves", (_r, id) => saves.filter((s) => s.game?.id === +id));
on("POST", "/saves/backup", () => {
  const b: S["BackupOut"] = { id: new Date().toISOString().slice(0, 16).replace(/[-:T]/g, ""), created_at: iso(now()), auto: false,
    bytes: saves.reduce((n, s) => n + (s.size ?? 0), 0),
    files: saves.map((s) => ({ rel: s.rel, size: s.size ?? 0, kind: s.kind, slot: s.slot, platform: s.platform, game_title: s.game?.title ?? null, modified_at: s.modified_at })) };
  backups.unshift(b);
  return b;
});
on("GET", "/saves/backups", () => backups);
on("DELETE", "/saves/backups/{id}", (_r, id) => { const i = backups.findIndex((b) => b.id === decodeURIComponent(id)); if (i >= 0) backups.splice(i, 1); });
on("POST", "/saves/restore", (r) => ({ restored: body<{ rel: string }>(r).rel, previous_copy: null }));
on("POST", "/saves/delete", (r) => { const path = body<{ path: string }>(r).path; saves = saves.filter((s) => s.path !== path); return { deleted: path, copy: path }; });
on("GET", "/saves/howto", () => [
  { action: "save_state", combo: ["Menu", "R1"] }, { action: "load_state", combo: ["Menu", "L1"] }, { action: "slot_next", combo: ["Menu", "R2"] },
  { action: "slot_prev", combo: ["Menu", "L2"] }, { action: "quit", combo: ["Menu", "Start"] }, { action: "menu", combo: ["Menu", "X"] },
]);
on("POST", "/device/screenshot", () => {
  const p = consoleState.playing;
  if (!p) throw new DemoError(409, "no_game_running", "Aucun jeu en cours sur la console.");
  const e = entry(p.id);
  return { game_id: e.id, title: e.game.title, shot: addShot(e, now()) };
});
on("GET", "/screenshots", () => [...shots].filter(([, list]) => list.length).map(([id, list]) => {
  const e = entry(id), p = platformOf(e.game.dir);
  return { game_id: id, title: e.game.title, platform_code: p.code, platform_label: p.label, shots: list };
}));
on("GET", "/games/{id}/screenshots", (_r, id) => shots.get(+id) ?? []);

// Ajouter des jeux
on("GET", "/uploads", () => uploads);
on("PUT", "/uploads", (r) => {
  const u = { id: `u${now()}${uploads.length}`, filename: r.q.get("filename") ?? "game.bin", size: Number(r.q.get("size") ?? 0),
    sha256: "demo", received_at: iso(now()) };
  uploads.push(u);
  return u;
});
on("DELETE", "/uploads/{id}", (_r, id) => { const i = uploads.findIndex((u) => u.id === id); if (i >= 0) uploads.splice(i, 1); });
on("POST", "/transfers/plan", (r) => plan(body<{ items: { upload_id: string; platform?: string | null }[] }>(r).items));
on("POST", "/transfers", (r) => startTransfers(body<{ items: S["StartItem"][] }>(r).items));
on("GET", "/transfers", () => transfers);
on("POST", "/transfers/{id}/cancel", (_r, id) => { const t = transfers.find((x) => x.id === +id)!; if (["queued", "running"].includes(t.status)) t.status = "cancelled"; return t; });
on("POST", "/transfers/{id}/retry", () => []);

// Manettes, Bluetooth, son
on("GET", "/players", () => ({ ...players, game_running: !!consoleState.playing }));
on("PUT", "/players", (r) => { players = { ...players, ...body<object>(r) }; return players; });
on("GET", "/bluetooth", () => bt);
on("POST", "/bluetooth/scan", () => {
  if (!btDevice("3C:A9:F4:77:10:C2")) bt.devices.push({ address: "3C:A9:F4:77:10:C2", name: "Retro Pad", icon: "input-gaming", kind: "gamepad", paired: false, trusted: false, connected: false, rssi: -62 });
  return bt;
});
on("POST", "/bluetooth/connect", (r) => { const d = btDevice(body<{ address: string }>(r).address); if (d) Object.assign(d, { paired: true, trusted: true, connected: true }); return bt; });
on("POST", "/bluetooth/disconnect", (r) => { const d = btDevice(body<{ address: string }>(r).address); if (d) d.connected = false; return bt; });
on("POST", "/bluetooth/forget", (r) => { bt.devices = bt.devices.filter((d) => d.address !== body<{ address: string }>(r).address); return bt; });
on("POST", "/bluetooth/audio-output", (r) => { bt.audio_output = body<{ address: string | null }>(r).address; return bt; });
on("POST", "/bluetooth/test-sound", () => ({ result: "played" }));
on("GET", "/sound", () => ({ ...sound, devices: bt.devices }));
on("PUT", "/sound", (r) => { sound = { ...sound, ...body<object>(r) }; return { ...sound, devices: bt.devices }; });
on("POST", "/sound/test", () => ({ result: consoleState.playing ? "in_use" : "played" }));
on("GET", "/phone", () => ({ devices: 0, listening: false, available: false }));
on("GET", "/pc-pads", () => ({ available: false, reason: "demo", pads: [], relays: [] }));

// Fiches de jeu
on("GET", "/games/{id}/controls", (_r, id) => controls(entry(+id)));
on("GET", "/games/{id}/video", (_r, id) => {
  const q = `${entry(+id).game.title} gameplay`;
  return { status: "not_found", query: q, search_url: `https://www.youtube.com/results?search_query=${encodeURIComponent(q)}`, videos: [] };
});
on("GET", "/settings/youtube", () => ({ configured: true }));
on("GET", "/cheats", () => ({ available: true, files: library.length, updated_at: iso(START - 3 * DAY), size: 1_200_000, license: "CC BY-SA 4.0", source_url: "https://romkade.com/" }));
on("GET", "/games/{id}/cheats", (_r, id) => cheats(entry(+id)));
on("POST", "/games/{id}/cheats/install", (_r, id) => ({ path: `/mnt/mmc/cheats/${entry(+id).game.title}.cht` }));
const knowledge = { games: library.length, found: 0, not_found: 0, errors: 0, pending: library.length, chunks: 0, auto_after_sync: false,
  job: { running: false, total: 0, done: 0, found: 0, current: null, stopping: false }, license: "CC BY-SA" };
on("GET", "/knowledge", () => knowledge);
on("GET", "/games/{id}/knowledge", () => ({ status: "none", fetched_at: null, error: null, chunks: 0, sources: [], sections: [] }));
on("GET", "/descriptions", () => ({ credentials: false, problem: null, provider: null, provider_label: null, model: null, batch: false, local: false,
  games: library.length, complete: library.length, pending: 0, estimate_usd: null, batches: [] }));
on("GET", "/settings/llm", () => ({ provider: null, model: null, base_url: null, ready: false, problem: NO_AI[getLang()], state: "none",
  last_error: null, tested_at: null, local: false, local_presets: {}, providers: [] }));

// ROMKADE Cloud (moteur local et mcp.romkade.com)
on("GET", "/cloud/agent", () => ({ supported: true, installed: true, server: "https://mcp.romkade.com", cloud: "https://mcp.romkade.com",
  version: "demo", latest: "demo", update: false }));
on("GET", "/cloud/likes/top", () => []);
on("GET", "/me/consoles", () => ({ consoles: [{ id: "demo", name: CONSOLE.name, model: CONSOLE.model, firmware: CONSOLE.firmware, online: true,
  games: library.length, last_seen: Math.round(now() / 1000) }] }));

// ---------------------------------------------------------------------------------------------------------------
// Branchement : fetch et EventSource du navigateur

const json = (data: Json, status = 200) =>
  data === undefined ? new Response(null, { status: 204 }) : new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

async function handle(method: string, path: string, q: URLSearchParams, bodyText: string | null): Promise<Response> {
  const req: Req = { method, path, q, body: bodyText ? JSON.parse(bodyText) : undefined };
  await new Promise((r) => setTimeout(r, 60 + Math.random() * 120));  // un vrai serveur ne répond pas en 0 ms
  try {
    if (path === "/assistant" || path.startsWith("/assistant/") || /\/(caption|analyze|description)$/.test(path) || path.startsWith("/settings/llm/")) {
      throw new DemoError(409, "llm_none", NO_AI[getLang()]);
    }
    for (const [m, re, h] of routes) {
      const match = path.match(re);
      if (m === method && match) return json(await h(req, match[1] ?? ""));
    }
    if (method === "DELETE" && path.startsWith("data:")) {  // capture supprimée (son adresse est une image data:)
      shots.forEach((list, id) => shots.set(id, list.filter((s) => s.url !== path)));
      return json(undefined);
    }
    throw new DemoError(403, "demo_unavailable", unavailable());
  } catch (e) {
    const err = e instanceof DemoError ? e : new DemoError(500, "demo_error", String(e));
    return json({ error: { code: err.code, message: err.message, details: {} } }, err.status);
  }
}

class DemoEventSource {
  private listeners: ((ev: MessageEvent) => void)[] = [];
  private feed = (data: string) => this.listeners.forEach((fn) => fn(new MessageEvent("transfers", { data })));
  constructor(public url: string) { transferListeners.add(this.feed); }
  addEventListener(_type: string, fn: (ev: MessageEvent) => void) { this.listeners.push(fn); }
  close() { transferListeners.delete(this.feed); }
}

export function installDemoServer(): void {
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, location.href);
    const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    const bodyText = typeof init?.body === "string" ? init.body : null;
    if (raw.startsWith("data:")) return realFetch(input, init);
    if (url.origin === location.origin && url.pathname.startsWith("/api/")) {
      return handle(method, url.pathname.slice(4), url.searchParams, bodyText);
    }
    if (raw.startsWith("/apidata:")) return handle(method, raw.slice(4), new URLSearchParams(), bodyText);
    if (url.hostname === "mcp.romkade.com") return handle(method, url.pathname.replace(/^\/api/, ""), url.searchParams, bodyText);
    if (url.hostname.endsWith(".supabase.co")) {
      return json({ code: 403, error_code: "demo", msg: unavailable(), message: unavailable() }, 403);
    }
    return realFetch(input, init);
  };
  (window as unknown as { EventSource: unknown }).EventSource = DemoEventSource;
}
