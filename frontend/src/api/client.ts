import type { components } from "./schema";

type S = components["schemas"];
export type Game = S["GameOut"];
export type GameDetail = S["GameDetailOut"];
export type GamesPage = S["GamesPageOut"];
export type CatalogPlatform = S["CatalogPlatformOut"];
export type CatalogStatus = S["CatalogStatusOut"];
export type ScanRun = S["ScanRunOut"];
export type ChangesPage = S["ChangesPageOut"];
export type DuplicateGroup = S["DuplicateGroupOut"];
export type Facets = S["FacetsOut"];
export type Settings = S["SettingsOut"];
export type DeviceSettings = S["DeviceSettings"];
export type HostKey = S["HostKeyOut"];
export type ConnectionTest = S["ConnectionTestOut"];
export type Upload = S["UploadOut"];
export type Plan = S["PlanOut"];
export type PlanItem = S["PlanItemOut"];
export type Transfer = S["TransferOut"];
export type StartItem = S["StartItem"];
export type Video = S["VideoOut"];
export type VideoLookup = S["VideoLookupOut"];
export type NowPlaying = S["NowPlayingOut"];
export type Save = S["SaveOut"];
export type SavesList = S["SavesOut"];
export type Backup = S["BackupOut"];
export type Hotkey = S["HotkeyOut"];
export type BtStatus = S["BtStatusOut"];
export type BtDevice = S["BtDeviceOut"];
export type Players = S["PlayersOut"];
export type Controller = S["ControllerOut"];
export type Volume = S["VolumeOut"];
export type Diagnose = S["DiagnoseOut"];
export type Clock = S["ClockOut"];
export type DescriptionsStatus = S["DescriptionsStatusOut"];
export type LlmSettings = S["LlmSettingsOut"];
export type LlmProvider = S["ProviderOut"];
export type LlmTest = S["LlmTestOut"];
export type PlayState = S["PlayStateOut"];
export type GameControls = S["GameControlsOut"];
export type KnowledgeStatus = S["KnowledgeStatusOut"];
export type GameKnowledge = S["GameKnowledgeOut"];
export type KnowledgeHit = S["KnowledgeHitOut"];
export type GameControlsIn = S["GameControlsIn"];
export type PlayStats = S["PlayStatsOut"];
export type PlaySettings = S["PlaySettings"];
export type RecentPlayed = S["RecentGameOut"];
export type SearchResult = S["SearchOut"];
export type DeviceSystem = S["DeviceSystemOut"];
export type SystemProfile = S["SystemProfileOut"];
export type Capabilities = S["CapabilitiesOut"];

/** Erreur structurée renvoyée par le backend : {"error": {code, message, details}}. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "backend_unreachable", "Le serveur local ne répond pas. Il est peut-être arrêté.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = data?.error;
    throw new ApiError(res.status, err?.code ?? "http_error", err?.message ?? `Erreur ${res.status}`, err?.details ?? {});
  }
  return data as T;
}

export type Query = Record<string, string | number | boolean | string[] | null | undefined>;

export function qs(params: Query): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, x));
    else sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  status: () => request<CatalogStatus>("GET", "/catalog/status"),
  platforms: () => request<CatalogPlatform[]>("GET", "/platforms"),
  games: (params: Query) => request<GamesPage>("GET", `/games${qs(params)}`),
  game: (id: number) => request<GameDetail>("GET", `/games/${id}`),
  favorites: (limit?: number) => request<Game[]>("GET", `/favorites${qs({ limit })}`),
  setFavorite: (id: number, on: boolean) => request<void>(on ? "PUT" : "DELETE", `/games/${id}/favorite`),
  facets: (platform: string[]) => request<Facets>("GET", `/catalog/facets${qs({ platform })}`),
  startSync: () => request<ScanRun>("POST", "/catalog/sync"),
  sync: (id: number) => request<ScanRun>("GET", `/catalog/sync/${id}`),
  syncs: () => request<ScanRun[]>("GET", "/catalog/syncs?limit=15"),
  changes: (params: Query) => request<ChangesPage>("GET", `/catalog/changes${qs(params)}`),
  duplicates: () => request<DuplicateGroup[]>("GET", "/catalog/duplicates"),
  deviceStatus: () => request<{ connected: boolean; error: { code: string; message: string } | null }>("GET", "/device/status"),
  settings: () => request<Settings>("GET", "/settings"),
  saveSettings: (s: DeviceSettings) => request<Settings>("PUT", "/settings", s),
  savePassword: (password: string) => request<void>("PUT", "/settings/password", { password }),
  hostKey: () => request<HostKey>("GET", "/device/host-key"),
  trustHostKey: (fingerprint: string) => request<HostKey>("POST", "/device/host-key/trust", { fingerprint }),
  testConnection: () => request<ConnectionTest>("POST", "/device/test-connection"),
  diagnose: () => request<Diagnose>("POST", "/device/diagnose"),
  clock: () => request<Clock>("GET", "/device/clock"),
  syncClock: (timezone: string | null) => request<Clock>("POST", "/device/clock/sync", { timezone }),
  uploads: () => request<Upload[]>("GET", "/uploads"),
  deleteUpload: (id: string) => request<void>("DELETE", `/uploads/${id}`),
  plan: (items: { upload_id: string; platform?: string | null }[]) => request<Plan>("POST", "/transfers/plan", { items }),
  startTransfers: (items: StartItem[], confirm_overwrite: boolean) =>
    request<Transfer[]>("POST", "/transfers", { items, confirm_overwrite }),
  transfers: () => request<Transfer[]>("GET", "/transfers?limit=60"),
  cancelTransfer: (id: number) => request<Transfer>("POST", `/transfers/${id}/cancel`),
  retryTransfer: (id: number) => request<Transfer[]>("POST", `/transfers/${id}/retry`),
  knowledge: () => request<KnowledgeStatus>("GET", "/knowledge"),
  knowledgeSettings: (auto_after_sync: boolean) => request<KnowledgeStatus>("PUT", "/knowledge/settings", { auto_after_sync }),
  startKnowledge: () => request<KnowledgeStatus>("POST", "/knowledge/start"),
  stopKnowledge: () => request<KnowledgeStatus>("POST", "/knowledge/stop"),
  gameKnowledge: (id: number) => request<GameKnowledge>("GET", `/games/${id}/knowledge`),
  fetchGameKnowledge: (id: number) => request<GameKnowledge>("POST", `/games/${id}/knowledge`),
  searchGameKnowledge: (id: number, q: string) => request<KnowledgeHit[]>("GET", `/games/${id}/knowledge/search${qs({ q })}`),
  gameControls: (id: number) => request<GameControls>("GET", `/games/${id}/controls`),
  generateControls: (id: number) => request<GameControls>("POST", `/games/${id}/controls`),
  editControls: (id: number, body: GameControlsIn) => request<GameControls>("PUT", `/games/${id}/controls`, body),
  gameVideo: (id: number, refresh = false) => request<VideoLookup>("GET", `/games/${id}/video${qs({ refresh: refresh || undefined })}`),
  youtubeSettings: () => request<{ configured: boolean }>("GET", "/settings/youtube"),
  saveYoutubeKey: (api_key: string) => request<void>("PUT", "/settings/youtube", { api_key }),
  deleteYoutubeKey: () => request<void>("DELETE", "/settings/youtube"),
  descriptions: () => request<DescriptionsStatus>("GET", "/descriptions"),
  startDescriptions: () => request<DescriptionsStatus>("POST", "/descriptions/start"),
  llmSettings: () => request<LlmSettings>("GET", "/settings/llm"),
  saveLlmSettings: (b: { provider: string | null; model?: string | null; base_url?: string | null }) =>
    request<LlmSettings>("PUT", "/settings/llm", b),
  saveLlmKey: (provider: string, api_key: string) => request<LlmSettings>("PUT", "/settings/llm/key", { provider, api_key }),
  deleteLlmKey: (provider: string) => request<LlmSettings>("DELETE", `/settings/llm/key/${encodeURIComponent(provider)}`),
  llmModels: (provider: string, base_url?: string | null) =>
    request<string[]>("GET", `/settings/llm/models?${new URLSearchParams({ provider, ...(base_url ? { base_url } : {}) })}`),
  testLlm: () => request<LlmTest>("POST", "/settings/llm/test"),
  launchGame: (id: number, slot?: string | null) =>
    request<{ status: string; rom_path: string }>("POST", `/games/${id}/launch`, slot ? { slot } : {}),
  playState: () => request<PlayState>("GET", "/play/state"),
  search: (q: string, limit = 8) => request<SearchResult>("GET", `/search${qs({ q, limit })}`),
  recentPlayed: (limit = 12) => request<RecentPlayed[]>("GET", `/play/recent?limit=${limit}`),
  playStats: (days = 14, period?: { start: string; end: string } | null) =>
    request<PlayStats>("GET", `/play/stats${qs({ days, start: period?.start, end: period?.end })}`),
  resetPlaytime: (games: { key: string; ra_seconds: number }[], everything = false) =>
    request<void>("POST", everything ? "/play/reset-all" : "/play/reset", { games }),
  playSettings: () => request<PlaySettings>("GET", "/play/settings"),
  savePlaySettings: (s: PlaySettings) => request<PlaySettings>("PUT", "/play/settings", s),
  ackAlert: (id: number) => request<void>("POST", `/play/alerts/${id}/ack`),
  bluetooth: () => request<BtStatus>("GET", "/bluetooth"),
  btScan: () => request<BtStatus>("POST", "/bluetooth/scan"),
  btConnect: (address: string) => request<BtStatus>("POST", "/bluetooth/connect", { address }),
  btDisconnect: (address: string) => request<BtStatus>("POST", "/bluetooth/disconnect", { address }),
  btForget: (address: string) => request<BtStatus>("POST", "/bluetooth/forget", { address }),
  btAudioOutput: (address: string | null) => request<BtStatus>("POST", "/bluetooth/audio-output", { address }),
  players: () => request<Players>("GET", "/players"),
  setPlayers: (players: number[]) => request<Players>("PUT", "/players", { players }),
  volume: () => request<Volume>("GET", "/volume"),
  setVolume: (body: { percent?: number; muted?: boolean }) => request<Volume>("PUT", "/volume", body),
  nowPlaying: () => request<NowPlaying>("GET", "/device/now-playing"),
  system: () => request<DeviceSystem>("GET", "/device/system"),
  systems: () => request<SystemProfile[]>("GET", "/systems"),
  detectSystem: () => request<DeviceSystem>("POST", "/device/system/detect"),
  quitGame: () => request<{ result: string }>("POST", "/device/quit-game"),
  saveStateNow: () => request<{ result: string }>("POST", "/device/save-state"),
  saves: () => request<SavesList>("GET", "/saves"),
  gameSaves: (id: number) => request<Save[]>("GET", `/games/${id}/saves`),
  backupSaves: (paths?: string[]) => request<Backup>("POST", "/saves/backup", { paths: paths ?? null }),
  backups: () => request<Backup[]>("GET", "/saves/backups"),
  deleteBackup: (id: string) => request<void>("DELETE", `/saves/backups/${encodeURIComponent(id)}`),
  restoreSave: (backup_id: string, rel: string) => request<{ restored: string; previous_copy: string | null }>("POST", "/saves/restore", { backup_id, rel }),
  deleteSave: (path: string) => request<{ deleted: string; copy: string }>("POST", "/saves/delete", { path }),
  saveHowto: () => request<Hotkey[]>("GET", "/saves/howto"),
};

/**
 * Envoie un fichier au serveur local (zone d'attente). XMLHttpRequest plutôt que fetch :
 * c'est la seule API du navigateur qui donne la progression d'un envoi.
 */
export function uploadFile(file: File, onProgress: (loaded: number, total: number) => void, signal?: AbortSignal): Promise<Upload> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `/api/uploads${qs({ filename: file.name })}`);
    xhr.upload.onprogress = (e) => onProgress(e.loaded, e.total || file.size);
    xhr.onload = () => {
      const data = (() => { try { return JSON.parse(xhr.responseText); } catch { return null; } })();
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as Upload);
      else reject(new ApiError(xhr.status, data?.error?.code ?? "http_error", data?.error?.message ?? `Erreur ${xhr.status}`, data?.error?.details));
    };
    xhr.onerror = () => reject(new ApiError(0, "backend_unreachable", "Le serveur local ne répond pas."));
    xhr.onabort = () => reject(new ApiError(0, "aborted", "Envoi annulé"));
    signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(file);
  });
}

export function imageUrl(game: Pick<Game, "image_url">, size: "thumb" | "full" = "thumb"): string | null {
  return game.image_url ? `${game.image_url}?size=${size}` : null;
}

export const saveFileUrl = (path: string) => `/api/saves/file${qs({ path })}`;
export const backupZipUrl = (id: string) => `/api/saves/backups/${encodeURIComponent(id)}/zip`;
