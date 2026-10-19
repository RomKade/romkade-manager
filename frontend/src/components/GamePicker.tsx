import { useState } from "react";

import { useQuickSearch } from "../api/queries";
import { useT } from "../i18n";
import { useDebounced } from "../lib/hooks";

export type PickedGame = { id: number; title: string; platform: string };

/** Choisir un jeu de la bibliothèque par la recherche (Paramètres : test sur un jeu, un seul jeu au lieu de tous). */
export function GamePicker({ id, onPick }: { id: string; onPick: (g: PickedGame) => void }) {
  const t = useT();
  const [text, setText] = useState("");
  const results = useQuickSearch(useDebounced(text, 200));
  return (
    <div className="game-picker">
      <label className="field game-picker__field" htmlFor={id}>
        <span className="field__label">{t("settings.kn.pick")}</span>
        <input id={id} type="search" value={text} placeholder={t("settings.kn.pickPlaceholder")} onChange={(e) => setText(e.target.value)} />
      </label>
      {text.trim() && (results.data?.items ?? []).length > 0 && (
        <ul className="game-picker__results">
          {results.data!.items.slice(0, 6).map((g) => (
            <li key={g.id}>
              <button type="button" className="link-button" onClick={() => {
                setText("");
                onPick({ id: g.id, title: g.title, platform: g.platform.label ?? g.platform.directory });
              }}>
                {g.title} <span className="muted">· {g.platform.label ?? g.platform.directory}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
