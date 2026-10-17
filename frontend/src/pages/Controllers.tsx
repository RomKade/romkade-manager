import { AlertTriangle, Gamepad2, Users } from "lucide-react";
import { Link } from "react-router-dom";

import type { Controller, Players } from "../api/client";
import { useCaps, useDeviceStatus, usePlayers, useSetPlayers } from "../api/queries";
import { ErrorNotice, PageHeader, Spinner } from "../components/ui";
import { useT } from "../i18n";

/** Manettes : qui contrôle le jeu, manette de chaque joueur dans RetroArch (voir backend app/device/players.py). */
export function ControllersPage() {
  const t = useT();
  const online = useDeviceStatus().data?.connected === true;
  const q = usePlayers(online);
  const save = useSetPlayers();
  const p = q.data;
  const builtin = p?.controllers.find((c) => c.builtin);
  const players = p ? complete(p.players) : [];
  const p1 = players[0] ?? 0;

  // Choisir une manette pour un joueur l'échange avec le joueur qui l'avait : deux joueurs n'ont jamais la même.
  const choose = (player: number, index: number) => {
    const next = [...players];
    const other = next.indexOf(index);
    if (other >= 0) next[other] = players[player]!;
    next[player] = index;
    save.mutate(next);
  };

  return (
    <div className="page controllers">
      <PageHeader title={t("players.title")} lead={t("players.lead")}>
        {builtin && p1 !== builtin.index && (
          <button type="button" className="button button--primary" disabled={save.isPending} onClick={() => choose(0, builtin.index)}>
            <Gamepad2 size={16} aria-hidden /> {t("players.useConsole")}
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
        <PlayersBlock p={p} players={players} busy={save.isPending} error={save.error} onChoose={choose} />
      )}
    </div>
  );
}

function PlayersBlock({ p, players, busy, error, onChoose }: {
  p: Players; players: number[]; busy: boolean; error: unknown; onChoose: (player: number, index: number) => void;
}) {
  const t = useT();
  const bluetooth = useCaps().bluetooth;
  const byIndex = new Map(p.controllers.map((c) => [c.index, c]));
  const label = (i: number) => {
    const c = byIndex.get(i);
    return c ? controllerName(c, t) : t("players.missing", { n: i });
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
            <li key={n} className="field">
              <label htmlFor={`player-${n}`} className="field__label">{t("players.player", { n: n + 1 })}</label>
              <select id={`player-${n}`} value={index} disabled={busy} onChange={(e) => onChoose(n, Number(e.target.value))}>
                {options.map((i) => <option key={i} value={i}>{label(i)}</option>)}
              </select>
            </li>
          ))}
        </ol>
        {error ? <ErrorNotice error={error} /> : !p.applied && <p className="muted">{t("players.pending")}</p>}
      </section>

      <section className="block" aria-labelledby="players-detected">
        <h2 id="players-detected">{t("players.detected")}</h2>
        {p.controllers.length === 0 ? <p className="muted">{t("players.noneDetected")}</p> : (
          <ul className="players__detected">
            {p.controllers.map((c) => <li key={c.index}><Gamepad2 size={16} aria-hidden /> {controllerName(c, t)}</li>)}
          </ul>
        )}
        {bluetooth && <p className="muted"><Link to="/bluetooth">{t("players.help")}</Link></p>}
      </section>
    </>
  );
}

function controllerName(c: Controller, t: ReturnType<typeof useT>): string {
  return c.builtin ? t("players.builtin") : `${c.name} · ${t("players.number", { n: c.index })}`;
}

/** Joueurs sans numéro dans la config : premier numéro libre. */
function complete(players: Players["players"]): number[] {
  const used = new Set(players.filter((i): i is number => i != null));
  let free = 0;
  return players.map((i) => {
    if (i != null) return i;
    while (used.has(free)) free++;
    used.add(free);
    return free;
  });
}
