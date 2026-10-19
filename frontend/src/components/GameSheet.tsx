import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { Copy, Download, Gamepad2, Loader2, Save, Square, Star, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { saveFileUrl, type GameDetail } from "../api/client";
import { useCaps, useDeviceStatus, useGame, useGameSaves, useLaunchGame, useNowPlaying, usePlayers, useQuitGame, useSaveStateNow, useSetFavorite, useSetPlayers } from "../api/queries";
import { useT } from "../i18n";
import { bytes, date, dateTime } from "../lib/format";
import { assignPlayer, completePlayers } from "../lib/players";
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
          {game.platform.label && <span>{game.platform.label}</span>}</p>
        {!game.present && <p className="tag tag--warn">{t("sheet.absent")}</p>}
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
 * Une manette branchée en plus des boutons de la console : « Jouer » demande d'abord qui joue (joueur 1), écrit
 * ce choix, puis lance le jeu, qui le prend en compte au démarrage de RetroArch.
 */
function LaunchButton({ id }: { id: number }) {
  const t = useT();
  const launch = useLaunchGame();
  const online = useDeviceStatus().data?.connected === true;
  const now = useNowPlaying(online).data;
  const caps = useCaps();
  const qc = useQueryClient();
  const [starting, setStarting] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const pq = usePlayers(online && caps.players);
  const savePlayers = useSetPlayers();
  const controllers = pq.data?.controllers ?? [];
  const players = pq.data ? completePlayers(pq.data.players) : [];
  const play = (index?: number) => {
    setChoosing(false);
    if (index == null || players[0] === index) launch.mutate(id);
    else savePlayers.mutate(assignPlayer(players, 0, index), { onSuccess: () => launch.mutate(id) });
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
  const busy = launch.isPending || savePlayers.isPending || starting;
  if (choosing) return (
    <div className="launch-choice" role="group" aria-labelledby="launch-choice-h">
      <p id="launch-choice-h" className="launch-choice__title">{t("sheet.whoPlays")}</p>
      <div className="launch-choice__options">
        {controllers.map((c) => (
          <button key={c.index} type="button" className={`button ${players[0] === c.index ? "button--primary" : ""}`}
            onClick={() => play(c.index)}>
            <Gamepad2 size={16} aria-hidden /> {c.builtin ? t("players.builtin") : c.name}
          </button>
        ))}
        <button type="button" className="button button--small" onClick={() => setChoosing(false)}>{t("sheet.controls.cancel")}</button>
      </div>
    </div>
  );
  return (
    <>
      <button type="button" className={`button button--primary ${busy ? "is-busy" : ""}`}
        onClick={() => (controllers.length > 1 ? setChoosing(true) : play())} disabled={busy} aria-busy={busy}>
        {busy ? <Loader2 size={16} aria-hidden className="spin" /> : <Gamepad2 size={16} aria-hidden />}{" "}
        <span role="status">{busy ? t("sheet.starting") : t("sheet.play")}</span>
      </button>
      {(launch.isError || savePlayers.isError) && <div className="sheet__launch-error">
        <ErrorNotice error={launch.error ?? savePlayers.error} title={t("sheet.launchFailed")} /></div>}
    </>
  );
}

/** Étoile de la fiche : met le jeu en favori ou l'en retire. */
function FavoriteButton({ id, on }: { id: number; on: boolean }) {
  const t = useT();
  const set = useSetFavorite(id);
  return (
    <button type="button" className={`button favorite-button ${on ? "is-on" : ""}`} aria-pressed={on}
      disabled={set.isPending} onClick={() => set.mutate(!on)}>
      <Star size={16} fill={on ? "currentColor" : "none"} aria-hidden /> {t(on ? "sheet.favorite.on" : "sheet.favorite.add")}
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
          {ra && caps.save_state && <button type="button" className="button button--small" onClick={() => save.mutate()} disabled={save.isPending}
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
