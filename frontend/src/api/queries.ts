import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { api, type Capabilities, type GameControls, type GameDetail, type KnowledgeStatus, type GameControlsIn, type Query, type Transfer } from "./client";

export const PAGE_SIZE = 120;

export const useStatus = () =>
  useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: (q) => (q.state.data?.sync_running ? 1500 : 30_000),
  });

export const usePlatforms = () => useQuery({ queryKey: ["platforms"], queryFn: api.platforms, staleTime: 60_000 });

/** Interroge la console toutes les 30 s (une connexion SSH courte, sans écriture). */
export const useDeviceStatus = () =>
  // Console absente : on la recherche plus souvent, pour la voir arriver vite (elle répond, ou échoue en ~8 s).
  useQuery({ queryKey: ["device-status"], queryFn: api.deviceStatus, retry: false,
    refetchInterval: (q) => (q.state.data?.connected ? 30_000 : 12_000) });

export const useFacets = (platform: string[]) =>
  useQuery({ queryKey: ["facets", platform], queryFn: () => api.facets(platform), staleTime: 60_000 });

export const useGamesInfinite = (params: Query, enabled = true) =>
  useInfiniteQuery({
    queryKey: ["games", params],
    enabled,
    queryFn: ({ pageParam }) => api.games({ ...params, offset: pageParam, limit: PAGE_SIZE }),
    initialPageParam: 0,
    getNextPageParam: (last) => {
      const next = last.page.offset + last.page.limit;
      return next < last.page.total ? next : undefined;
    },
    placeholderData: keepPreviousData,
  });

/** Jeux favoris, le dernier ajouté en tête. */
export const useFavorites = (limit?: number) =>
  useQuery({ queryKey: ["favorites", limit], queryFn: () => api.favorites(limit) });

export function useSetFavorite(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (on: boolean) => api.setFavorite(id, on),
    onSuccess: (_, on) => {
      qc.setQueryData<GameDetail>(["game", id], (g) => (g ? { ...g, favorite: on } : g));
      qc.invalidateQueries({ queryKey: ["favorites"] });
      qc.invalidateQueries({ queryKey: ["games"] });
    },
  });
}

export const useRecentGames = (limit = 14) =>
  useQuery({ queryKey: ["games", "recent", limit], queryFn: () => api.games({ sort: "added", order: "desc", limit }) });

export const useGame = (id: number | null) =>
  useQuery({ queryKey: ["game", id], queryFn: () => api.game(id!), enabled: id != null });

/** Bandes-annonces : la première demande lance une recherche YouTube (quota), la réponse est en cache côté serveur. */
export const useGameVideo = (id: number | null) =>
  useQuery({ queryKey: ["game-video", id], queryFn: () => api.gameVideo(id!), enabled: id != null, staleTime: Infinity, retry: false });

/** Connaissances pour l'assistant (Wikipédia, StrategyWiki) : couverture et récupération en cours. */
export const useKnowledge = () =>
  useQuery({ queryKey: ["knowledge"], queryFn: api.knowledge,
    refetchInterval: (q) => (q.state.data?.job.running ? 2000 : false) });

export function useKnowledgeMutations() {
  const qc = useQueryClient();
  const onSuccess = (d: KnowledgeStatus) => qc.setQueryData(["knowledge"], d);
  return {
    start: useMutation({ mutationFn: (refresh: boolean = false) => api.startKnowledge(refresh), onSuccess }),
    stop: useMutation({ mutationFn: api.stopKnowledge, onSuccess }),
    auto: useMutation({ mutationFn: api.knowledgeSettings, onSuccess }),
  };
}

/** Commandes du jeu (quelle touche fait quoi) : rédigées par Claude à la demande ou corrigées à la main. */
export const useCheatsStatus = () => useQuery({ queryKey: ["cheats"], queryFn: api.cheatsStatus });
export const useGameCheats = (id: number) =>
  useQuery({ queryKey: ["game-cheats", id], queryFn: () => api.gameCheats(id), staleTime: Infinity, retry: false });

/** Téléchargement (ou mise à jour) du paquet des codes de triche de RetroArch. */
export function useDownloadCheats() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.downloadCheats,
    onSuccess: (d) => { qc.setQueryData(["cheats"], d); qc.invalidateQueries({ queryKey: ["game-cheats"] }); },
  });
}

export const useGameControls = (id: number) =>
  useQuery({ queryKey: ["game-controls", id], queryFn: () => api.gameControls(id), staleTime: Infinity, retry: false });

export function useControlsMutations(id: number) {
  const qc = useQueryClient();
  const onSuccess = (d: GameControls) => qc.setQueryData(["game-controls", id], d);
  return {
    generate: useMutation({ mutationFn: () => api.generateControls(id), onSuccess }),
    edit: useMutation({ mutationFn: (body: GameControlsIn) => api.editControls(id, body), onSuccess }),
  };
}

/** Jeu en cours sur la console (une connexion SSH courte, sans écriture), seulement si elle est joignable. */
export const useNowPlaying = (enabled: boolean) =>
  useQuery({ queryKey: ["now-playing"], queryFn: api.nowPlaying, enabled, refetchInterval: 15_000, retry: false });

export function useLaunchGame() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: number | { id: number; slot?: string | null }) =>
      typeof v === "number" ? api.launchGame(v) : api.launchGame(v.id, v.slot),
    // le jeu met quelques secondes à démarrer : on relit l'état à plusieurs reprises
    onSuccess: () => [3000, 7000, 12000].forEach((ms) => setTimeout(() => {
      qc.invalidateQueries({ queryKey: ["now-playing"] });
      qc.invalidateQueries({ queryKey: ["recent-played"] });
      qc.invalidateQueries({ queryKey: ["players"] });
    }, ms)),
  });
}

export function useQuitGame() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: api.quitGame, onSuccess: () => qc.invalidateQueries({ queryKey: ["now-playing"] }) });
}

export function useSaveStateNow() {
  return useMutation({ mutationFn: api.saveStateNow });
}

/** Sauvegardes de la carte : une lecture SFTP de quelques dossiers, relancée à la demande. */
export const useSaves = (enabled = true) =>
  useQuery({ queryKey: ["saves"], queryFn: api.saves, enabled, staleTime: 60_000, retry: false });
export const useGameSaves = (id: number | null) =>
  useQuery({ queryKey: ["saves", "game", id], queryFn: () => api.gameSaves(id!), enabled: id != null, retry: false });
export const useBackups = () => useQuery({ queryKey: ["save-backups"], queryFn: api.backups });
export const useSaveHowto = (enabled = true) =>
  useQuery({ queryKey: ["save-howto"], queryFn: api.saveHowto, enabled, staleTime: Infinity, retry: false });

export function useSaveMutations() {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["saves"] });
    qc.invalidateQueries({ queryKey: ["save-backups"] });
  };
  return {
    backup: useMutation({ mutationFn: (paths?: string[]) => api.backupSaves(paths), onSuccess: refresh }),
    restore: useMutation({ mutationFn: (v: { backup: string; rel: string }) => api.restoreSave(v.backup, v.rel), onSuccess: refresh }),
    remove: useMutation({ mutationFn: (path: string) => api.deleteSave(path), onSuccess: refresh }),
    removeBackup: useMutation({ mutationFn: (id: string) => api.deleteBackup(id), onSuccess: refresh }),
  };
}

/** Temps de jeu : état léger (lu sur le serveur, sans contacter la console), relu toutes les 30 s. */
export const usePlayState = () =>
  useQuery({ queryKey: ["play-state"], queryFn: api.playState, refetchInterval: 30_000, retry: false });
export const usePlayStats = (days = 14, period: { start: string; end: string } | null = null) =>
  useQuery({ queryKey: ["play-stats", days, period], queryFn: () => api.playStats(days, period), refetchInterval: 60_000, retry: false });

/** Remet à zéro le temps de jeu de jeux (clé + total RetroArch des statistiques), ou tout. */
export function useResetPlaytime() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ games, everything = false }: { games: { key: string; ra_seconds: number }[]; everything?: boolean }) =>
      api.resetPlaytime(games, everything),
    onSuccess: () => ["play-stats", "play-state", "recent-played"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })),
  });
}
/** Recherche rapide (Typesense quand il est prêt), pour le tableau de bord. */
export const useQuickSearch = (q: string) =>
  useQuery({ queryKey: ["search", q], queryFn: () => api.search(q), enabled: q.trim().length > 0,
    placeholderData: keepPreviousData, staleTime: 30_000 });

/** Jeux joués récemment (historique RetroArch de la console + parties suivies par Game Manager). */
export const useRecentPlayed = () =>
  useQuery({ queryKey: ["recent-played"], queryFn: () => api.recentPlayed(12), refetchInterval: 60_000, retry: false });

export const usePlaySettings = () => useQuery({ queryKey: ["play-settings"], queryFn: api.playSettings });

export function useSavePlaySettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.savePlaySettings,
    onSuccess: (s) => {
      qc.setQueryData(["play-settings"], s);
      qc.invalidateQueries({ queryKey: ["play-state"] });
    },
  });
}

export function useAckAlert() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: api.ackAlert, onSuccess: () => qc.invalidateQueries({ queryKey: ["play-state"] }) });
}

/** Bluetooth de la console. Chaque opération renvoie l'état à jour. */
export const useBluetooth = (enabled: boolean) =>
  useQuery({ queryKey: ["bluetooth"], queryFn: api.bluetooth, enabled, retry: false, refetchInterval: 20_000 });

export function useBluetoothActions() {
  const qc = useQueryClient();
  const set = (data: Awaited<ReturnType<typeof api.bluetooth>>) => {
    qc.setQueryData(["bluetooth"], data);
    qc.invalidateQueries({ queryKey: ["players"] });  // une manette connectée ou partie change la liste
  };
  return {
    scan: useMutation({ mutationFn: api.btScan, onSuccess: set }),
    // Un échec peut quand même avoir appairé l'appareil : on relit l'état.
    connect: useMutation({ mutationFn: api.btConnect, onSuccess: set, onError: () => qc.invalidateQueries({ queryKey: ["bluetooth"] }) }),
    disconnect: useMutation({ mutationFn: api.btDisconnect, onSuccess: set }),
    forget: useMutation({ mutationFn: api.btForget, onSuccess: set }),
    audio: useMutation({ mutationFn: api.btAudioOutput, onSuccess: set }),
  };
}

/** Manette de chaque joueur (RetroArch). Relu avec le Bluetooth : une manette connectée change la liste. */
export const usePlayers = (enabled: boolean) =>
  useQuery({ queryKey: ["players"], queryFn: api.players, enabled, retry: false, refetchInterval: 20_000 });

export function useSetPlayers() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: api.setPlayers, onSuccess: (d) => qc.setQueryData(["players"], d) });
}

/** Volume du son des jeux (console ou appareil Bluetooth). */
export const useVolume = (enabled: boolean) =>
  useQuery({ queryKey: ["volume"], queryFn: api.volume, enabled, retry: false, refetchInterval: 30_000 });

export function useSetVolume() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: api.setVolume, onSuccess: (d) => qc.setQueryData(["volume"], d) });
}

export const useLlmSettings = () => useQuery({ queryKey: ["llm-settings"], queryFn: api.llmSettings });
export const useYoutubeSettings = () => useQuery({ queryKey: ["youtube-settings"], queryFn: api.youtubeSettings });

export const useSyncs = () => useQuery({ queryKey: ["syncs"], queryFn: api.syncs });

export const useChanges = (runId: number | undefined, change?: string) =>
  useQuery({
    queryKey: ["changes", runId, change],
    queryFn: () => api.changes({ run_id: runId, change, limit: 200 }),
    enabled: runId != null,
  });

export const useDuplicates = () => useQuery({ queryKey: ["duplicates"], queryFn: api.duplicates });

export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: api.settings });

/** Système de la console (firmware) et ce que Game Manager sait y faire. */
export const useSystem = () => useQuery({ queryKey: ["system"], queryFn: api.system, staleTime: 5 * 60_000, retry: false });
export const useSystems = () => useQuery({ queryKey: ["systems"], queryFn: api.systems, staleTime: Infinity });
const ALL_CAPS: Capabilities = {
  launch: true, resume_slot: true, quit: true, save_state: true, now_playing: true, saves: true,
  retroarch_logs: true, bluetooth: true, bluetooth_audio: true, players: true, volume: true, on_screen_message: true, clock: true,
};
/** Fonctions disponibles. Tant que le système n'est pas connu, tout reste affiché (le serveur refuse proprement). */
export const useCaps = (): Capabilities => useSystem().data?.capabilities ?? ALL_CAPS;
export function useDetectSystem() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: api.detectSystem, onSuccess: (d) => qc.setQueryData(["system"], d) });
}

export function useStartSync(onStarted: (id: number) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.startSync,
    onSuccess: (run) => {
      onStarted(run.id);
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["syncs"] });
    },
  });
}

export const useUploads = () => useQuery({ queryKey: ["uploads"], queryFn: api.uploads });

export const ACTIVE_STATUSES = ["queued", "running", "verifying"] as const;
export const isActive = (t: Transfer) => (ACTIVE_STATUSES as readonly string[]).includes(t.status);

export const useTransfers = () => useQuery({ queryKey: ["transfers"], queryFn: api.transfers, refetchInterval: 15_000 });

/** Branché une seule fois (dans la mise en page) : tient la liste des transferts à jour en direct. */
export function useTransfersLive() {
  const qc = useQueryClient();
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const es = new EventSource("/api/transfers/events");
    let activeIds: string | null = null;
    es.addEventListener("transfers", (ev) => {
      const { active, finished } = JSON.parse((ev as MessageEvent).data) as { active: Transfer[]; finished: number };
      const ids = `${active.map((t) => t.id).join(",")}|${finished}`;
      qc.setQueryData<Transfer[]>(["transfers"], (old) => {
        if (!old) return old;
        const byId = new Map(active.map((t) => [t.id, t]));
        const merged = old.map((t) => byId.get(t.id) ?? t);
        const known = new Set(old.map((t) => t.id));
        return [...active.filter((t) => !known.has(t.id)), ...merged];
      });
      if (ids !== activeIds) {
        // Un transfert a commencé ou s'est terminé : on relit l'historique et ce qui dépend du catalogue.
        if (activeIds !== null) {
          for (const k of ["transfers", "uploads", "status", "games", "platforms", "facets", "syncs"]) qc.invalidateQueries({ queryKey: [k] });
        }
        activeIds = ids;
      }
    });
    return () => es.close();
  }, [qc]);
}
