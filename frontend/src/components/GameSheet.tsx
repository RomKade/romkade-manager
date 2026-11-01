import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { Ban, ChevronRight, Copy, Download, Gamepad2, Info, KeyRound, Lightbulb, Loader2, type LucideIcon, MessageCircle,
  Play, CirclePlus, Save, Settings, Square, Star, ThumbsDown, ThumbsUp, TriangleAlert, Users, X } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { saveFileUrl, type GameDetail } from "../api/client";
import { useCaps, useDeviceStatus, useGame, useGameCheats, useGameSaves, useLaunchGame, useNowPlaying, usePlayers, useQuitGame, useSaveStateNow, useSetBroken, useSetDislike, useSetFavorite, useSetLike, useSetPlayers } from "../api/queries";
import { useT } from "../i18n";
import { bytes, date, dateTime } from "../lib/format";
import { controllerLabel, dropUnusedRelays, linkComputerPad, padName, useComputerPads, useRelays } from "../lib/computerPads";
import { assignPlayer, completePlayers, defaultSlots, PLAYERS } from "../lib/players";
import { saveLabel } from "../lib/saves";
import { ConsoleBadge } from "./ConsoleBadge";
import { Cover } from "./Cover";
import { assistant, useAssistant } from "../lib/assistant";
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

/**
 * Fiche d'un jeu : en tête, le jeu en images sur toute la largeur (étoile des favoris et Fermer par-dessus) ; la
 * jaquette, qui chevauche le bas des images, à côté du titre ; puis « Jouer » (« Reprendre la partie » quand une
 * instantanée auto existe) à côté de l'état de la console ; puis des groupes repliables (manettes, commandes, codes,
 * sauvegardes, à propos, fichier) ; en bas « Signaler un problème » et les pouces.
 */
function SheetBody({ game, onOpen, onVideo }: { game: GameDetail; onOpen: (id: number) => void; onVideo?: (game: GameDetail) => void }) {
  const t = useT();
  const [copied, setCopied] = useState(false);
  const candidate = game.role === "candidate";
  const launch = useLaunch(game.id);
  const regions = game.region ? game.region.split(", ") : [];
  const copyPath = async () => {
    await navigator.clipboard?.writeText(game.remote_path);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const trailer = Boolean(game.youtube_url || onVideo);

  return (
    <div className="sheet__body">
      <GameGallery key={game.id} game={game} />
      {candidate && <FavoriteStar id={game.id} on={game.favorite ?? false} />}

      <div className="sheet__ident">
        <Cover key={game.id} game={game} size="full" className="sheet__cover" />
        <div className="sheet__head">
          <Dialog.Title className="sheet__title">{game.title}</Dialog.Title>
          <p className="sheet__platform"><ConsoleBadge code={game.platform.code} label={game.platform.label} />
            {game.platform.label && <span>{game.platform.label}</span>}
            {regions.length > 0 && <span>{regions.map((r) => t(`common.region.${r}`)).join(", ")}</span>}
            <PlayersTag players={game.players ?? null} link={game.players_link} /></p>
          {!game.present && <p className="tag tag--warn">{t("sheet.absent")}</p>}
          {game.broken && <p className="tag tag--broken"><Ban size={14} aria-hidden /> {t("sheet.broken.tag")}</p>}
        </div>
      </div>

      {candidate && <PlayPanel game={game} launch={launch} />}

      <div className="sheet__groups">
        {candidate && launch.online && launch.options.length > 0 && (
          <Group icon={Gamepad2} title={t("sheet.group.players")} sub={t("sheet.group.players.sub")} open>
            <PlayersPicker launch={launch} />
          </Group>
        )}
        {candidate && <HelpGroup game={game} />}
        {candidate && <CheatsGroup id={game.id} />}
        {candidate && <SavesGroup id={game.id} online={launch.online} />}
        <Group icon={Info} title={t("sheet.group.about")}
          sub={[t("sheet.group.about.summary"), trailer && t("sheet.trailer")].filter(Boolean).join(" · ")}>
          {trailer && (
            <TrailerButton game={game} onVideo={onVideo} className="link-button sheet__trailer">
              <YoutubeIcon size={16} className="yt-icon--brand" /> {t("sheet.trailer")}
            </TrailerButton>
          )}
          <GameInfo game={game} />
          <GameScreenshots id={game.id} title={game.title} />
        </Group>
        <Group icon={Settings} title={t("sheet.group.file")}
          sub={[game.extension?.toUpperCase(), bytes(game.size)].filter(Boolean).join(" · ")}>
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
        </Group>
      </div>

      {candidate && (
        <div className="sheet__foot">
          <BrokenButton id={game.id} on={game.broken ?? false} />
          <Reactions id={game.id} liked={game.liked ?? false} disliked={game.disliked ?? false} />
        </div>
      )}
    </div>
  );
}

/** Groupe repliable de la fiche : pictogramme, titre et résumé d'une ligne ; le contenu s'ouvre en dessous. */
function Group({ icon: Icon, title, sub, open = false, children }: {
  icon: LucideIcon; title: string; sub?: string; open?: boolean; children: ReactNode;
}) {
  return (
    <details className="sheet__group" open={open}>
      <summary>
        <Icon size={22} aria-hidden className="sheet__group-icon" />
        <span className="sheet__group-text">
          <strong>{title}</strong>
          {sub && <span>{sub}</span>}
        </span>
        <ChevronRight size={20} aria-hidden className="sheet__group-chevron" />
      </summary>
      <div className="sheet__group-body">{children}</div>
    </details>
  );
}

/** Commandes du jeu, et l'assistant ouvert sur ce jeu (sauf s'il est masqué dans les paramètres). */
function HelpGroup({ game }: { game: GameDetail }) {
  const t = useT();
  const { name, hidden } = useAssistant();
  const ask = () => {
    assistant.setScope({ kind: "game", game: { id: game.id, title: game.title, platform: game.platform.label ?? game.platform.directory } });
    assistant.setOpen(true);
  };
  return (
    <Group icon={Lightbulb} title={t("sheet.group.help")}
      sub={hidden ? t("sheet.group.help.subAlone") : t("sheet.group.help.sub", { name })}>
      <GameControlsSection id={game.id} />
      {!hidden && (
        <button type="button" className="button button--small sheet__ask" onClick={ask}>
          <MessageCircle size={14} aria-hidden /> {t("sheet.askAssistant", { name })}
        </button>
      )}
    </Group>
  );
}

function CheatsGroup({ id }: { id: number }) {
  const t = useT();
  const data = useGameCheats(id).data;
  const count = data?.files[0]?.count ?? 0;
  const sub = !data ? undefined : !data.available ? t("sheet.group.cheats.download") : count === 0 ? t("sheet.group.cheats.none")
    : count === 1 ? t("sheet.group.cheats.one") : t("sheet.group.cheats.many", { count });
  return (
    <Group icon={KeyRound} title={t("sheet.cheats.title")} sub={sub}>
      <GameCheatsSection id={id} />
    </Group>
  );
}

/** Sauvegardes de ce jeu sur la console (lecture seule), avec un lien vers la page Sauvegardes. */
function SavesGroup({ id, online }: { id: number; online: boolean }) {
  const t = useT();
  const saves = useGameSaves(online ? id : null);
  const kinds = [...new Set((saves.data ?? []).map((s) => saveLabel(t, s)))];
  const sub = !online ? t("sheet.console.offline") : saves.isPending ? t("saves.scanning")
    : saves.data ? (kinds.length ? kinds.join(" · ") : t("sheet.group.saves.none")) : undefined;
  return (
    <Group icon={Save} title={t("saves.title")} sub={sub}>
      {!online ? <p className="muted">{t("sheet.group.saves.offline")}</p>
        : saves.isPending ? <Spinner label={t("saves.scanning")} /> : saves.isError ? <ErrorNotice error={saves.error} /> :
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
    </Group>
  );
}

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

type Launch = ReturnType<typeof useLaunch>;

/**
 * Lancement depuis la fiche, partagé par « Jouer » et le groupe « Manettes et joueurs ». Raccourci de la page
 * Manettes : plusieurs manettes possibles (boutons de la console, manettes branchées, manettes de l'ordinateur) ;
 * chaque joueur (jusqu'à 4) a sa manette ; « Jouer » écrit ce choix (en relayant d'abord les manettes de
 * l'ordinateur), puis lance le jeu, qui le prend en compte au démarrage de RetroArch.
 */
function useLaunch(id: number) {
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
  const initial = defaultSlots(players, options, PLAYERS);
  const [touched, setTouched] = useState<string[] | null>(null);
  // "" : aucune manette pour ce joueur (libère une manette pour la donner à un autre joueur).
  const draft = touched && touched.length === PLAYERS && touched.every((v) => v === "" || options.includes(v)) ? touched : initial;
  const pick = (n: number, value: string) => {
    const next = [...draft];
    const other = value === "" ? -1 : next.indexOf(value);
    if (other >= 0) next[other] = next[n]!;  // échange avec le joueur qui l'avait (option grisée, par sécurité)
    next[n] = value;
    setTouched(next);
  };
  /** `slot` : instantanée à charger au démarrage (« auto » pour reprendre la partie), sinon démarrage normal. */
  const play = async (slot: string | null = null) => {
    const start = () => launch.mutate(slot ? { id, slot } : id);
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
      if (final.every((v, i) => v === base[i])) start();
      else savePlayers.mutate(final, { onSuccess: (d) => { dropUnusedRelays(d); start(); } });
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
  return {
    online, caps, options, draft, pick, optionLabel, play, linkError,
    playing: now?.playing === true && now.game?.id === id,
    // Un seul état visible de l'envoi au démarrage du jeu (jusqu'à ce que le bandeau « En cours » prenne le relais).
    busy: launch.isPending || savePlayers.isPending || starting || linking,
    error: launch.isError || savePlayers.isError ? (launch.error ?? savePlayers.error) : null,
  };
}

/**
 * Sous le titre : l'état de la console (et l'instantanée auto de RetroArch quand il y en a une) à gauche, « Reprendre
 * la partie » (ou démarrer normalement) ou « Jouer » à droite. Le bandeau « En cours » le remplace quand ce jeu tourne.
 */
function PlayPanel({ game, launch }: { game: GameDetail; launch: Launch }) {
  const t = useT();
  const { online, caps, busy } = launch;
  const saves = useGameSaves(online ? game.id : null);
  if (launch.playing) return <div className="sheet__play"><PlayingBanner gameId={game.id} /></div>;
  const auto = caps.resume_slot
    ? saves.data?.find((s) => s.kind === "state" && s.slot === "auto" && s.source === "retroarch") : undefined;
  const canLaunch = game.present && caps.launch;
  return (
    <div className="sheet__play">
      <div className="sheet__play-state">
        <p className={`sheet__status ${online ? "is-online" : "is-offline"}`}>
          <span className="led" aria-hidden /> {t(online ? "sheet.console.online" : "sheet.console.offline")}
        </p>
        {auto && <p className="muted">{saveLabel(t, auto)} · {dateTime(auto.modified_at)}</p>}
        {game.present && !caps.launch && <p className="muted">{t("sheet.launchUnavailable")}</p>}
      </div>
      {canLaunch && (
        <div className="sheet__play-actions">
          <button type="button" className={`button button--primary sheet__play-button ${busy ? "is-busy" : ""}`}
            onClick={() => launch.play(auto ? "auto" : null)} disabled={busy} aria-busy={busy}>
            {busy ? <Loader2 size={18} aria-hidden className="spin" /> : <Play size={18} fill="currentColor" aria-hidden />}{" "}
            <span role="status">{busy ? t("sheet.starting") : t(auto ? "sheet.resume" : "sheet.play")}</span>
          </button>
          {auto && (
            <button type="button" className="link-button sheet__play-alt" onClick={() => launch.play(null)} disabled={busy}>
              {t("sheet.playNormally")}
            </button>
          )}
        </div>
      )}
      {launch.linkError && <p className="players__warn sheet__play-error">{launch.linkError}</p>}
      {launch.error && <div className="sheet__play-error"><ErrorNotice error={launch.error} title={t("sheet.launchFailed")} /></div>}
    </div>
  );
}

/** Une ligne par joueur qui a une manette ; « Ajouter un joueur » en montre un de plus (jusqu'à 4). */
function PlayersPicker({ launch }: { launch: Launch }) {
  const t = useT();
  const { draft, options, pick, optionLabel } = launch;
  const [shown, setShown] = useState(1);
  const used = draft.reduce((m, v, n) => (v ? n + 1 : m), 0);
  const count = Math.min(PLAYERS, Math.max(shown, used));
  return (
    <fieldset className="launch-who" disabled={launch.busy}>
      <legend className="visually-hidden">{t("sheet.whoPlays")}</legend>
      {draft.slice(0, count).map((value, n) => (
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
      {count < PLAYERS && (
        <button type="button" className="link-button launch-who__add" onClick={() => setShown(count + 1)}>
          <CirclePlus size={18} aria-hidden /> {t("sheet.addPlayer")}
        </button>
      )}
    </fieldset>
  );
}

/** Étoile en tête de fiche, à côté de Fermer : met le jeu en favori ou l'en retire. */
function FavoriteStar({ id, on }: { id: number; on: boolean }) {
  const t = useT();
  const set = useSetFavorite(id);
  return (
    <button type="button" className={`icon-button favorite-button sheet__fav ${on ? "is-on" : ""}`} aria-pressed={on}
      disabled={set.isPending} onClick={() => set.mutate(!on)} aria-label={t(on ? "sheet.favorite.on" : "sheet.favorite.add")}
      title={t(on ? "sheet.favorite.on" : "sheet.favorite.add")}>
      <Star size={22} fill={on ? "currentColor" : "none"} aria-hidden />
    </button>
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

/**
 * Pouce en haut (« J'aime ») et pouce en bas (« Je n'aime pas ») : l'un retire l'autre ; « Je n'aime pas » retire
 * aussi le favori. Comptent dans le classement des plus aimés de tous les comptes (avec l'accord de l'utilisateur).
 */
function Reactions({ id, liked, disliked }: { id: number; liked: boolean; disliked: boolean }) {
  const t = useT();
  const like = useSetLike(id);
  const dislike = useSetDislike(id);
  const busy = like.isPending || dislike.isPending;
  return (
    <span className="sheet__reactions" role="group" aria-label={t("sheet.reactions")}>
      <button type="button" className={`icon-button like-button ${liked ? "is-on" : ""}`} aria-pressed={liked} disabled={busy}
        onClick={() => like.mutate(!liked)} aria-label={t(liked ? "sheet.like.undo" : "sheet.like.add")}
        title={t(liked ? "sheet.like.undo" : "sheet.like.add")}>
        <ThumbsUp size={20} fill={liked ? "currentColor" : "none"} aria-hidden />
      </button>
      <button type="button" className={`icon-button dislike-button ${disliked ? "is-on" : ""}`} aria-pressed={disliked} disabled={busy}
        onClick={() => dislike.mutate(!disliked)} aria-label={t(disliked ? "sheet.dislike.undo" : "sheet.dislike.add")}
        title={t(disliked ? "sheet.dislike.undo" : "sheet.dislike.hint")}>
        <ThumbsDown size={20} fill={disliked ? "currentColor" : "none"} aria-hidden />
      </button>
    </span>
  );
}

/** Pied de fiche : signale le jeu comme ne fonctionnant pas sur cette console (ou retire le signalement). */
function BrokenButton({ id, on }: { id: number; on: boolean }) {
  const t = useT();
  const set = useSetBroken(id);
  return (
    <button type="button" className={`link-button sheet__report ${on ? "is-on" : ""}`} aria-pressed={on}
      disabled={set.isPending} onClick={() => set.mutate(!on)} title={t(on ? "sheet.broken.undo" : "sheet.broken.hint")}>
      <TriangleAlert size={16} aria-hidden /> {t(on ? "sheet.broken.on" : "sheet.report")}
    </button>
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
        {caps.quit && <>
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
