import type { Controller, Players } from "../api/client";

/** Joueurs sans numéro dans la config : premier numéro libre. */
export function completePlayers(players: Players["players"]): number[] {
  const used = new Set(players.filter((i): i is number => i != null));
  let free = 0;
  return players.map((i) => {
    if (i != null) return i;
    while (used.has(free)) free++;
    used.add(free);
    return free;
  });
}

/** Donne la manette `index` au joueur `player` ; le joueur qui l'avait prend la sienne : jamais deux joueurs sur
 * la même manette. */
export function assignPlayer(players: number[], player: number, index: number): number[] {
  const next = [...players];
  const other = next.indexOf(index);
  if (other >= 0) next[other] = players[player]!;
  next[player] = index;
  return next;
}

export function controllerName(c: Controller, t: (key: string, vars?: Record<string, string | number>) => string): string {
  return c.builtin ? t("players.builtin") : `${c.name} · ${t("players.number", { n: c.index })}`;
}
