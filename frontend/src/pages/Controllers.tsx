import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Gamepad2, Library, RotateCcw, Users } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { Controller, Players } from "../api/client";
import { useCaps, useDeviceStatus, useLaunchGame, useNowPlaying, usePlayers, useSetDirections, useSetPlayers } from "../api/queries";
import { ErrorNotice, PageHeader, Spinner } from "../components/ui";
import { useT } from "../i18n";
import {
  type ComputerRelay, controllerLabel, dropUnusedRelays, gamepadsSupported, linkComputerPad, padName, type PcPad, serverPadsActive,
  useComputerPads, useRelays,
} from "../lib/computerPads";
import { assignPlayer, completePlayers } from "../lib/players";

/** Manettes : qui contrôle le jeu, manette de chaque joueur dans RetroArch (voir backend app/device/players.py). */
export function ControllersPage() {
  const t = useT();
  const online = useDeviceStatus().data?.connected === true;
  const q = usePlayers(online);
  const save = useSetPlayers();
  const steer = useSetDirections();
  const p = q.data;
  const builtin = p?.controllers.find((c) => c.builtin);
  const players = p ? completePlayers(p.players) : [];
  const p1 = players[0] ?? 0;
  const caps = useCaps();
  const navigate = useNavigate();
  const now = useNowPlaying(online).data;
  const launch = useLaunchGame();

  // Le changement ne vaut qu'au prochain lancement de RetroArch : un jeu RetroArch connu de la bibliothèque peut
  // être relancé tout de suite (launch.sh le quitte proprement, applique les manettes, puis reprend la partie).
  const game = now?.playing && now.process === "retroarch" ? now.game : null;
  const canRelaunch = !!game && caps.launch;
  const relaunch = () => game && launch.mutate({ id: game.id, slot: caps.resume_slot ? "auto" : null });
  const qc = useQueryClient();
  const relays = useRelays();
  const [linking, setLinking] = useState(false);
  const [linkError, setLinkError] = useState("");
  const busy = save.isPending || steer.isPending || launch.isPending || linking;

  // Choisir une manette pour un joueur l'échange avec le joueur qui l'avait : deux joueurs n'ont jamais la même.
  // Une manette de l'ordinateur que plus aucun joueur n'utilise n'est plus relayée.
  const choose = (player: number, index: number, then?: () => void) =>
    save.mutate(assignPlayer(players, player, index), { onSuccess: (d) => { dropUnusedRelays(d); then?.(); } });
  // Manette de l'ordinateur : on la relaie vers la console, puis on donne au joueur la manette virtuelle créée.
  const chooseComputer = async (player: number, pad: PcPad) => {
    setLinking(true);
    setLinkError("");
    try {
      const { players: d, index } = await linkComputerPad(pad, t);
      qc.setQueryData(["players"], d);
      dropUnusedRelays(await save.mutateAsync(assignPlayer(completePlayers(d.players), player, index)));
    } catch (e) {
      setLinkError((e as Error).message);
    } finally {
      setLinking(false);
    }
  };
  // Ce qui dirige un joueur ; les autres gardent le leur (inconnu : croix seule, le réglage par défaut de RetroArch).
  const direct = (player: number, direction: number) =>
    p && steer.mutate(p.directions.map((d, n) => (n === player ? direction : d ?? 0)));

  // Un seul bouton d'en-tête. Changement en attente pendant un jeu : relancer le jeu. Joueur 1 sur une manette
  // absente (la console ne contrôle plus rien) : rendre la main aux boutons de la console. Sinon, sans jeu en
  // cours : choisir un jeu dans la bibliothèque.
  const p1Missing = !!p && !p.controllers.some((c) => c.index === p1);
  let cta: { label: string; icon: typeof Gamepad2; run: () => void } | null = null;
  if (canRelaunch && p && !p.applied) {
    cta = { label: t("players.relaunch"), icon: RotateCcw, run: relaunch };
  } else if (builtin && p1Missing) {
    cta = !now?.playing
      ? { label: t("players.useConsole"), icon: Gamepad2, run: () => choose(0, builtin.index, () => navigate("/bibliotheque")) }
      : canRelaunch
        ? { label: t("players.useConsoleRelaunch"), icon: RotateCcw, run: () => choose(0, builtin.index, relaunch) }
        : { label: t("players.useConsole"), icon: Gamepad2, run: () => choose(0, builtin.index) };
  } else if (p && !now?.playing && caps.launch) {
    cta = { label: t("players.pickGame"), icon: Library, run: () => navigate("/bibliotheque") };
  }

  return (
    <div className="page controllers">
      <PageHeader title={t("players.title")} lead={t("players.lead")}>
        {cta && (
          <button type="button" className="button button--primary" disabled={busy} onClick={cta.run}>
            <cta.icon size={16} aria-hidden /> {launch.isPending ? t("players.relaunching") : cta.label}
          </button>
        )}
      </PageHeader>

      {!online ? (
        <p className="muted">{t("players.offline")}</p>
      ) : q.isPending ? (
        <Spinner label={t("players.reading")} />
      ) : q.isError ? (
        <ErrorNotice error={q.error} />
      ) : p && (
        <PlayersBlock p={p} players={players} busy={busy} error={save.error ?? steer.error ?? launch.error}
          canRelaunch={canRelaunch} onChoose={(n, i) => choose(n, i)} onDirection={direct}
          relays={relays} linking={linking} linkError={linkError} onComputer={chooseComputer} />
      )}
    </div>
  );
}

/** input_playerN_analog_dpad_mode de RetroArch : 0 croix seule, 1 + stick gauche, 2 + stick droit. */
const DIRECTIONS = ["dpad", "dpadLeft", "dpadRight"] as const;

function PlayersBlock({ p, players, busy, error, canRelaunch, onChoose, onDirection, relays, linking, linkError, onComputer }: {
  p: Players; players: number[]; busy: boolean; error: unknown; canRelaunch: boolean;
  onChoose: (player: number, index: number) => void; onDirection: (player: number, direction: number) => void;
  relays: ComputerRelay[]; linking: boolean; linkError: string; onComputer: (player: number, pad: PcPad) => void;
}) {
  const t = useT();
  const bluetooth = useCaps().bluetooth;
  const byIndex = new Map(p.controllers.map((c) => [c.index, c]));
  const name = (c: Controller) => controllerLabel(c, relays, t);
  const label = (i: number) => {
    const c = byIndex.get(i);
    return c ? name(c) : t("players.missing", { n: i });
  };
  // Manettes de l'ordinateur pas encore relayées : les choisir les relaie vers la console.
  const pads = useComputerPads().filter((g) => !relays.some((r) => r.pad === g.index));
  const pick = (n: number, value: string) => {
    const pad = value.startsWith("pc:") ? pads.find((g) => g.index === Number(value.slice(3))) : null;
    if (pad) onComputer(n, pad);
    else if (!value.startsWith("pc:")) onChoose(n, Number(value));
  };
  const p1 = players[0] ?? 0;
  const options = [...new Set([...p.controllers.map((c) => c.index), ...players])].sort((x, y) => x - y);

  return (
    <>
      <section className="block players" aria-labelledby="players-title">
        <div>
          <h2 id="players-title"><Users size={18} aria-hidden /> {t("players.question")}</h2>
          <p className="muted">{t("players.playersLead")}</p>
        </div>
        {!byIndex.has(p1) && (
          <p className="players__warn"><AlertTriangle size={16} aria-hidden /> {t("players.p1Missing", { name: label(p1) })}</p>
        )}
        <ol className="players__list">
          {players.map((index, n) => (
            <li key={n} className="players__player">
              <div className="field">
                <label htmlFor={`player-${n}`} className="field__label">{t("players.player", { n: n + 1 })}</label>
                <select id={`player-${n}`} value={String(index)} disabled={busy} onChange={(e) => pick(n, e.target.value)}>
                  {/* Manette branchée d'un autre joueur : grisée, avec son joueur (une manette ne sert qu'à un joueur).
                      Un numéro sans manette branchée reste libre : le choisir libère la manette du joueur. */}
                  {options.map((i) => {
                    const other = players.indexOf(i);
                    const taken = other >= 0 && other !== n && byIndex.has(i);
                    return <option key={i} value={String(i)} disabled={taken}>
                      {taken ? t("players.takenBy", { name: label(i), n: other + 1 }) : label(i)}</option>;
                  })}
                  {pads.map((g) => (
                    <option key={`pc:${g.index}`} value={`pc:${g.index}`}>{t("players.computerPad", { name: padName(g) })}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor={`direction-${n}`} className="field__label">{t("players.direction")}</label>
                <select id={`direction-${n}`} value={p.directions[n] ?? 0} disabled={busy}
                  onChange={(e) => onDirection(n, Number(e.target.value))}>
                  {DIRECTIONS.map((d, i) => <option key={d} value={i}>{t(`players.${d}`)}</option>)}
                </select>
              </div>
            </li>
          ))}
        </ol>
        <p className="muted">{t("players.directionLead")}</p>
        {/* Le navigateur ne montre une manette de l'ordinateur qu'après un appui sur un de ses boutons, page ouverte
            (protection de la vie privée) : aucun bouton « Rafraîchir » ne peut la faire apparaître plus tôt. */}
        {(serverPadsActive() || gamepadsSupported()) && (
          <p className={`players__pc ${pads.length ? "is-seen" : ""}`} role="status">
            <Gamepad2 size={16} aria-hidden />
            {pads.length
              ? t("players.computerSeen", { name: pads.map(padName).join(", ") })
              : t(serverPadsActive() ? "players.computerNone" : "players.computerPress")}
          </p>
        )}
        {(serverPadsActive() || gamepadsSupported()) && (
          <p className="muted">{t(serverPadsActive() ? "players.computerHintServer" : "players.computerHint")}</p>
        )}
        {linking && <p className="muted" role="status">{t("players.computerLinking")}</p>}
        {linkError && <p className="players__warn"><AlertTriangle size={16} aria-hidden /> {linkError}</p>}
        {error ? <ErrorNotice error={error} /> : !p.applied && <p className="muted">{t(canRelaunch ? "players.pendingRelaunch" : "players.pending")}</p>}
      </section>

      <section className="block" aria-labelledby="players-detected">
        <h2 id="players-detected">{t("players.detected")}</h2>
        {p.controllers.length === 0 ? <p className="muted">{t("players.noneDetected")}</p> : (
          <ul className="players__detected">
            {p.controllers.map((c) => <li key={c.index}><Gamepad2 size={16} aria-hidden /> {name(c)}</li>)}
          </ul>
        )}
        {bluetooth && <p className="muted"><Link to="/bluetooth">{t("players.help")}</Link></p>}
      </section>
    </>
  );
}
