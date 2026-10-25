import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { Ban, Copy, Download, Gamepad2, Loader2, Save, Square, Star, Users, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { saveFileUrl, type GameDetail } from "../api/client";
import { useCaps, useDeviceStatus, useGame, useGameSaves, useLaunchGame, useNowPlaying, usePlayers, useQuitGame, useSaveStateNow, useSetBroken, useSetFavorite, useSetPlayers } from "../api/queries";
import { useT } from "../i18n";
import { bytes, date, dateTime } from "../lib/format";
import { controllerLabel, dropUnusedRelays, linkComputerPad, padName, useComputerPads, useRelays } from "../lib/computerPads";
import { assignPlayer, completePlayers, defaultSlots, PLAYERS } from "../lib/players";
import { saveLabel } from "../lib/saves";
import { ConsoleBadge } from "./ConsoleBadge";
import { assistant } from "../lib/assistant";
import { AssistantBubble } from "./AssistantBubble";
import { GameCheatsSection } from "./GameCheats";
import { GameControlsSection } from "./GameControls";
import { GameInfo } from "./GameInfo";
import { GameGallery } from "./GameGallery";
import { GameScreenshots, ScreenshotButton } from "./Screenshots";
import { PlaySaveButton } from "./PlaySaveButton";
import { TrailerButton, YoutubeIcon } from "./Trailer";
import { ErrorNotice, Spinner } from "./ui";
import { VolumeControl } from "./VolumeControl";

const CHANGE_LABEL = {
  added: "sheet.change.added",
  modified: "sheet.change.modified",
  removed: "sheet.change.removed",
  restored: "sheet.change.restored",
};
const ROLE_LABEL = {
  candidate: "sheet.role.candidate",
  component: "sheet.role.component",
  auxiliary: "sheet.role.auxiliary",
  program: "sheet.role.program",
};

export function GameSheet({ id, onClose, onOpen, onVideo }: {
  id: number | null; onClose: () => void; onOpen: (id: number) => void; onVideo?: (game: GameDetail) => void;
}) {
  const t = useT();
  const q = useGame(id);
  // L'assistant sait quel jeu est ouvert (il propose d'en discuter) ; seule la fiche qui l'a annoncé l'efface.
  const announced = useRef(false);
  const g = id != null ? q.data : undefined;
  useEffect(() => {
    if (g) {
      assistant.setSheet({ id: g.id, title: g.title, platform: g.platform.label ?? g.platform.directory });
      announced.current = true;
    } else if (announced.current) {
      assistant.setSheet(null);
      announced.current = false;
    }
  }, [g]);
  useEffect(() => () => { if (announced.current) assistant.setSheet(null); }, []);
  return (
    <Dialog.Root open={id != null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="sheet-overlay" />
        <Dialog.Content className="sheet" aria-describedby={undefined}>
          <Dialog.Close className="icon-button sheet__close" aria-label={t("sheet.close")}>
            <X size={18} aria-hidden />
          </Dialog.Close>
          {q.isPending && <Spinner label={t("sheet.loading")} />}
          {q.isError && (
            <>
              <Dialog.Title className="visually-hidden">{t("sheet.unavailable")}</Dialog.Title>
              <ErrorNotice error={q.error} />
            </>
          )}
          {q.data && <SheetBody game={q.data} onOpen={onOpen} onVideo={onVideo} />}
          {id != null && <AssistantBubble placement="sheet" onOpenGame={onOpen} />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function SheetBody({ game, onOpen, onVideo }: { game: GameDetail; onOpen: (id: number) => void; onVideo?: (game: GameDetail) => void }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const copyPath = async () => {
    await navigator.clipboard?.writeText(game.remote_path);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="sheet__body">
      {/* Titre, puis console, au-dessus des images ; sous les images : bande-annonce (lien) et source de la jaquette. */}
      <div className="sheet__head">
        <Dialog.Title className="sheet__title">{game.title}</Dialog.Title>
        <p className="sheet__platform"><ConsoleBadge code={game.platform.code} label={game.platform.label} />
          {game.platform.label && <span>{game.platform.label}</span>}
          <PlayersTag players={game.players ?? null} link={game.players_link} /></p>
        {!game.present && <p className="tag tag--warn">{t("sheet.absent")}</p>}
        {game.broken && <p className="tag tag--broken"><Ban size={14} aria-hidden /> {t("sheet.broken.tag")}</p>}
      </div>
      <GameGallery key={game.id} game={game} left={
        <TrailerButton game={game} onVideo={onVideo} className="link-button sheet__trailer">
          <YoutubeIcon size={16} className="yt-icon--brand" /> {t("sheet.trailer")}
        </TrailerButton>
      } />
      <PlayingBanner gameId={game.id} />
      {game.role === "candidate" && (
        <div className="sheet__actions">
          {game.present && <LaunchButton id={game.id} />}
          <FavoriteButton id={game.id} on={game.favorite ?? false} />
          <BrokenButton id={game.id} on={game.broken ?? false} />
        </div>
      )}

      <GameInfo game={game} />

      {game.role === "candidate" && <GameControlsSection id={game.id} />}
      {game.role === "candidate" && <GameCheatsSection id={game.id} />}
      <GameScreenshots id={game.id} title={game.title} />

      <dl className="facts">
        {game.full_title && <div className="facts__wide"><dt>{t("sheet.fullTitle")}</dt><dd>{game.full_title}</dd></div>}
        <div><dt>{t("sheet.file")}</dt><dd className="break">{game.filename}</dd></div>
        <div><dt>{t("sheet.type")}</dt><dd>{t(ROLE_LABEL[game.role])}</dd></div>
        <div><dt>{t("sheet.format")}</dt><dd>{game.extension ? `.${game.extension}` : t("sheet.noExtension")}</dd></div>
        <div><dt>{t("sheet.size")}</dt><dd className="num">{bytes(game.size)}</dd></div>
        <div><dt>{t("sheet.modified")}</dt><dd>{date(game.modified_at)}</dd></div>
        <div><dt>{t("sheet.firstSeen")}</dt><dd>{dateTime(game.first_seen_at)}</dd></div>
        <div className="facts__wide">
          <dt>{t("sheet.location")}</dt>
          <dd className="path">
            <code className="break">{game.remote_path}</code>
            <button type="button" className="icon-button" onClick={copyPath} aria-label={t("sheet.copyPath")}>
              <Copy size={15} aria-hidden />
            </button>
            {copied && <span className="path__copied" role="status">{t("sheet.copied")}</span>}
          </dd>
        </div>
      </dl>


      <GameSaves id={game.id} />

      {game.possible_duplicates.length > 0 && (
        <section className="sheet__section" aria-labelledby="dup-h">
          <h2 id="dup-h">{t("sheet.duplicates")}</h2>
          <ul className="dup-list">
            {game.possible_duplicates.map((d) => (
              <li key={d.id}>
                <button type="button" className="link-button" onClick={() => onOpen(d.id)}>
                  {d.filename}
                </button>
                <span className="muted num">{bytes(d.size)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="sheet__section" aria-labelledby="hist-h">
        <h2 id="hist-h">{t("sheet.history")}</h2>
        <ol className="timeline">
          {game.history.map((h, i) => (
            <li key={i}>
              <span>{t(CHANGE_LABEL[h.change])}</span>
              <span className="muted">{dateTime(h.run_started_at)}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

/**
 * Disparaît quand ce jeu tourne (le bandeau « En cours » prend le relais) ; bloqué pendant son démarrage.
 * Raccourci de la page Manettes : plusieurs manettes possibles (boutons de la console, manettes branchées, manettes
 * de l'ordinateur) : « Qui joue ? » donne une manette à chaque joueur (jusqu'à 4) ; « Jouer » écrit ce choix (en
 * relayant d'abord les manettes de l'ordinateur), puis lance le jeu, qui le prend en compte au démarrage de RetroArch.
 */
/** Sous le titre, à côté de la console : 1 joueur, jusqu'à N joueurs, ou à plusieurs avec câble link. Inconnu : rien. */
function PlayersTag({ players, link }: { players: number | null; link: boolean }) {
  const t = useT();
  if (!players) return null;
  const label = players === 1 ? t("sheet.tag.players.one") : t(link ? "sheet.tag.players.link" : "sheet.tag.players.many", { count: players });
  return (
    <span className={`tag tag--players ${players > 1 ? "is-multi" : ""}`}
      title={players > 1 ? t(link ? "sheet.info.players.link" : "sheet.tag.players.hint", { count: players }) : undefined}>
      <Users size={13} aria-hidden /> {label}
    </span>
  );
}

function LaunchButton({ id }: { id: number }) {
  const t = useT();
  const launch = useLaunchGame();
  const online = useDeviceStatus().data?.connected === true;
  const now = useNowPlaying(online).data;
  const caps = useCaps();
  const qc = useQueryClient();
  const [starting, setStarting] = useState(false);
  const [linking, setLinking] = useState(false);
  const [linkError, setLinkError] = useState("");
  const pq = usePlayers(online && caps.players);
  const savePlayers = useSetPlayers();
  const relays = useRelays();
  const controllers = pq.data?.controllers ?? [];
  const players = pq.data ? completePlayers(pq.data.players) : [];
  // Manettes de l'ordinateur pas encore relayées : les choisir les relaie vers la console.
  const pads = useComputerPads().filter((g) => !relays.some((r) => r.pad === g.index));
  // Une liste par joueur, les 4 joueurs comme sur la page Manettes : chaque manette est à un seul joueur, les
  // joueurs en trop sont sur « Aucune manette ».
  const options = [...controllers.map((c) => String(c.index)), ...pads.map((g) => `pc:${g.index}`)];
  const slots = PLAYERS;
  const initial = defaultSlots(players, options, slots);
  const [touched, setTouched] = useState<string[] | null>(null);
  // "" : aucune manette pour ce joueur (libère une manette pour la donner à un autre joueur).
  const draft = touched && touched.length === slots && touched.every((v) => v === "" || options.includes(v)) ? touched : initial;
  const pick = (n: number, value: string) => {
    const next = [...draft];
    const other = value === "" ? -1 : next.indexOf(value);
    if (other >= 0) next[other] = next[n]!;  // échange avec le joueur qui l'avait (option grisée, par sécurité)
    next[n] = value;
    setTouched(next);
  };
  const play = async () => {
    setLinkError("");
    setLinking(true);
    try {
      // Manettes de l'ordinateur choisies : relayées d'abord, pour connaître leur numéro sur la console.
      let current = pq.data;
      const index = new Map<string, number>();
      for (const value of draft) {
        const pad = value.startsWith("pc:") ? pads.find((g) => g.index === Number(value.slice(3))) : null;
        if (!pad) continue;
        const linked = await linkComputerPad(pad, t);
        qc.setQueryData(["players"], linked.players);
        current = linked.players;
        index.set(value, linked.index);
      }
      const base = current ? completePlayers(current.players) : players;
      const chosen = draft.reduce((acc, v, n) => (v === "" ? acc : assignPlayer(acc, n, index.get(v) ?? Number(v))), base);
      // Joueur sans manette : un numéro où rien n'est branché, que personne n'a.
      const connected = new Set([...controllers.map((c) => c.index), ...index.values()]);
      const final = chosen.map((v, n) => {
        if (draft[n] !== "" || !connected.has(v)) return v;
        let free = 0;
        while (connected.has(free) || chosen.includes(free)) free++;
        chosen[n] = free;
        return free;
      });
      setTouched(null);
      if (final.every((v, i) => v === base[i])) launch.mutate(id);
      else savePlayers.mutate(final, { onSuccess: (d) => { dropUnusedRelays(d); launch.mutate(id); } });
    } catch (e) {
      setLinkError((e as Error).message);
    } finally {
      setLinking(false);
    }
  };
  const optionLabel = (value: string) => {
    if (value.startsWith("pc:")) {
      const g = pads.find((x) => x.index === Number(value.slice(3)));
      return t("players.computerPad", { name: g ? padName(g) : "" });
    }
    const c = controllers.find((x) => x.index === Number(value));
    return c ? controllerLabel(c, relays, t) : value;
  };
  // « Démarrage… » reste affiché jusqu'à ce que la console annonce ce jeu (le bandeau « En cours » prend alors
  // le relais), en relisant l'état toutes les 2 s ; au plus 60 s si le jeu ne démarre pas.
  useEffect(() => {
    if (!launch.isSuccess) return;
    setStarting(true);
    const poll = setInterval(() => qc.invalidateQueries({ queryKey: ["now-playing"] }), 2000);
    const timer = setTimeout(() => setStarting(false), 60_000);
    return () => { clearInterval(poll); clearTimeout(timer); };
  }, [launch.isSuccess, launch.submittedAt, qc]);
  if (now?.playing && now.game?.id === id) return null;
  if (!caps.launch) return <p className="muted">{t("sheet.launchUnavailable")}</p>;
  // Un seul état visible de l'envoi au démarrage du jeu (jusqu'à ce que le bandeau « En cours » prenne le relais).
  const busy = launch.isPending || savePlayers.isPending || starting || linking;
  return (
    <>
      {options.length > 1 && (
        <fieldset className="launch-who" disabled={busy}>
          <legend>{t("sheet.whoPlays")}</legend>
          {draft.map((value, n) => (
            <label key={n} className="launch-who__player">
              <span>{t("players.player", { n: n + 1 })}</span>
              <select value={value} onChange={(e) => pick(n, e.target.value)}>
                <option value="">{t("players.none")}</option>
                {options.map((o) => {
                  const other = draft.indexOf(o);
                  const taken = other >= 0 && other !== n;
                  return <option key={o} value={o} disabled={taken}>
                    {taken ? t("players.takenBy", { name: optionLabel(o), n: other + 1 }) : optionLabel(o)}</option>;
                })}
              </select>
            </label>
          ))}
        </fieldset>
      )}
      <button type="button" className={`button button--primary ${busy ? "is-busy" : ""}`}
        onClick={play} disabled={busy} aria-busy={busy}>
        {busy ? <Loader2 size={16} aria-hidden className="spin" /> : <Gamepad2 size={16} aria-hidden />}{" "}
        <span role="status">{busy ? t("sheet.starting") : t("sheet.play")}</span>
      </button>
      {linkError && <p className="sheet__launch-error players__warn">{linkError}</p>}
      {(launch.isError || savePlayers.isError) && <div className="sheet__launch-error">
        <ErrorNotice error={launch.error ?? savePlayers.error} title={t("sheet.launchFailed")} /></div>}
    </>
  );
}

/** Étoile de la fiche (et du jeu en cours, au tableau de bord) : met le jeu en favori ou l'en retire. */
export function FavoriteButton({ id, on, small = false }: { id: number; on: boolean; small?: boolean }) {
  const t = useT();
  const set = useSetFavorite(id);
  return (
    <button type="button" className={`button ${small ? "button--small " : ""}favorite-button ${on ? "is-on" : ""}`} aria-pressed={on}
      disabled={set.isPending} onClick={() => set.mutate(!on)}>
      <Star size={16} fill={on ? "currentColor" : "none"} aria-hidden /> {t(on ? "sheet.favorite.on" : "sheet.favorite.add")}
    </button>
  );
}

/** Signale le jeu comme ne fonctionnant pas sur cette console (ou retire le signalement). */
function BrokenButton({ id, on }: { id: number; on: boolean }) {
  const t = useT();
  const set = useSetBroken(id);
  return (
    <button type="button" className={`button broken-button ${on ? "is-on" : ""}`} aria-pressed={on}
      disabled={set.isPending} onClick={() => set.mutate(!on)} title={t(on ? "sheet.broken.undo" : "sheet.broken.hint")}>
      <Ban size={16} aria-hidden /> {t(on ? "sheet.broken.on" : "sheet.broken.add")}
    </button>
  );
}

/** Sauvegardes de ce jeu sur la console (lecture seule), avec un lien vers la page Sauvegardes. */
function GameSaves({ id }: { id: number }) {
  const t = useT();
  const online = useDeviceStatus().data?.connected === true;
  const saves = useGameSaves(online ? id : null);
  if (!online) return null;
  return (
    <section className="sheet__section" aria-labelledby="saves-h">
      <h2 id="saves-h">{t("saves.title")}</h2>
      {saves.isPending ? <Spinner label={t("saves.scanning")} /> : saves.isError ? <ErrorNotice error={saves.error} /> :
        saves.data.length === 0 ? <p className="muted">{t("saves.noneForGame")}</p> : (
          <ul className="dup-list">
            {saves.data.map((s) => (
              <li key={s.path}>
                <span>{saveLabel(t, s)}</span>
                <span className="muted num">{dateTime(s.modified_at)}</span>
                <PlaySaveButton save={s} />
                <a className="icon-button" href={saveFileUrl(s.path)} download aria-label={t("saves.download")}><Download size={14} aria-hidden /></a>
              </li>
            ))}
          </ul>
        )}
      <Link to={`/sauvegardes?game=${id}`} className="link">{t("saves.manage")}</Link>
    </section>
  );
}

/** Bandeau « En cours sur la console » quand ce jeu tourne, avec Sauvegarder, Quitter, Capture d'écran et le volume. */
function PlayingBanner({ gameId }: { gameId: number }) {
  const t = useT();
  const online = useDeviceStatus().data?.connected === true;
  const now = useNowPlaying(online).data;
  const quit = useQuitGame();
  const save = useSaveStateNow();
  const caps = useCaps();
  if (!now?.playing || now.game?.id !== gameId) return null;
  const ra = now.process === "retroarch";
  return (
    <div className="playing-banner" role="status">
      <span className="led led--live" aria-hidden />
      <strong>{t("dashboard.nowPlaying")}</strong>
      <span className="playing-banner__actions">
        {(ra || !caps.resume_slot) && caps.quit && <>
          {ra && caps.save_state && <button type="button" className="button button--small button--save" onClick={() => save.mutate()} disabled={save.isPending}
            aria-label={save.isSuccess ? t("dashboard.saved") : t("dashboard.saveNow")} title={t("dashboard.saveNow")}>
            <Save size={14} aria-hidden /> {save.isSuccess ? t("dashboard.savedShort") : t("dashboard.saveShort")}
          </button>}
          <button type="button" className="button button--small button--danger" onClick={() => quit.mutate()} disabled={quit.isPending}
            aria-label={t("common.device.quit")} title={t("common.device.quit")}>
            <Square size={14} fill="currentColor" aria-hidden /> {t("common.device.quitShort")}
          </button>
        </>}
        <ScreenshotButton variant="small" />
      </span>
      <div className="playing-banner__volume"><VolumeControl online={online} /></div>
    </div>
  );
}
