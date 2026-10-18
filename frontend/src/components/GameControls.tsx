import { Gamepad2, Loader2, Pencil, Plus, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import type { GameControls } from "../api/client";
import { useControlsMutations, useGameControls } from "../api/queries";
import { getLang, useT } from "../i18n";
import { ErrorNotice } from "./ui";

type Button = GameControls["controls"][number]["button"];
const BUTTONS: Button[] = ["dpad", "left_stick", "right_stick", "a", "b", "x", "y", "l1", "r1", "l2", "r2", "l3", "r3",
  "start", "select"];
type Row = { button: Button; text: string };

/** Fiche du jeu : quelle touche de la console fait quoi dans ce jeu (Claude à la demande, corrigeable à la main). */
export function GameControlsSection({ id }: { id: number }) {
  const t = useT();
  const q = useGameControls(id);
  const { generate, edit } = useControlsMutations(id);
  const [editing, setEditing] = useState<Row[] | null>(null);
  const [notes, setNotes] = useState("");
  const data = q.data;
  const lang = getLang();
  if (!data) return null;

  const startEdit = () => {
    setEditing(data.controls.length ? data.controls.map((c) => ({ button: c.button, text: c[lang] }))
      : [{ button: "dpad", text: "" }, { button: "a", text: "" }, { button: "b", text: "" }]);
    setNotes(data.notes?.[lang] ?? "");
  };
  const save = () => {
    const controls = (editing ?? []).filter((r) => r.text.trim()).map((r) => ({ button: r.button, text: r.text.trim() }));
    if (controls.length) edit.mutate({ controls, notes: notes.trim() }, { onSuccess: () => setEditing(null) });
  };
  const setRow = (i: number, patch: Partial<Row>) => setEditing((rows) => rows!.map((r, n) => (n === i ? { ...r, ...patch } : r)));

  return (
    <section className="sheet__section controls" aria-labelledby="controls-h">
      <h2 id="controls-h"><Gamepad2 size={18} aria-hidden /> {t("sheet.controls.title")}</h2>

      {editing ? (
        <form className="controls__edit" onSubmit={(e) => { e.preventDefault(); save(); }}>
          {editing.map((r, i) => (
            <div key={i} className="controls__edit-row">
              <select aria-label={t("sheet.controls.button")} value={r.button} onChange={(e) => setRow(i, { button: e.target.value as Button })}>
                {BUTTONS.map((b) => <option key={b} value={b}>{t(`sheet.controls.key.${b}`)}</option>)}
              </select>
              <input aria-label={t("sheet.controls.action")} value={r.text} maxLength={120}
                placeholder={t("sheet.controls.actionPlaceholder")} onChange={(e) => setRow(i, { text: e.target.value })} />
              <button type="button" className="icon-button" aria-label={t("sheet.controls.removeRow")}
                onClick={() => setEditing((rows) => rows!.filter((_, n) => n !== i))}>
                <Trash2 size={15} aria-hidden />
              </button>
            </div>
          ))}
          <button type="button" className="link-button controls__add" onClick={() => setEditing((rows) => [...rows!, { button: "x", text: "" }])}>
            <Plus size={14} aria-hidden /> {t("sheet.controls.addRow")}
          </button>
          <textarea aria-label={t("sheet.controls.notes")} placeholder={t("sheet.controls.notesPlaceholder")} rows={2}
            maxLength={600} value={notes} onChange={(e) => setNotes(e.target.value)} />
          <div className="controls__actions">
            <button type="submit" className="button button--primary button--small" disabled={edit.isPending}>{t("sheet.controls.save")}</button>
            <button type="button" className="button button--small" onClick={() => setEditing(null)}>{t("sheet.controls.cancel")}</button>
          </div>
          {edit.isError && <ErrorNotice error={edit.error} />}
        </form>
      ) : (
        <>
          {data.status === "found" ? (
            <>
              <ul className="controls__list">
                {data.controls.map((c, i) => (
                  <li key={i}>
                    <kbd className={`controls__key controls__key--${c.button}`}>{t(`sheet.controls.key.${c.button}`)}</kbd>
                    <span>{c[lang]}</span>
                  </li>
                ))}
              </ul>
              {data.notes?.[lang] && <p className="controls__notes">{data.notes[lang]}</p>}
              <p className="muted controls__origin">
                {t(`sheet.controls.origin.${data.origin}`)}
                {data.origin === "sourced" && data.sources && data.sources.length > 0 && <>
                  {" "}{data.sources.map((s, i) => (
                    <span key={s.url}>{i > 0 && ", "}
                      <a href={s.url} target="_blank" rel="noreferrer noopener">
                        {t(`settings.kn.source.${s.source}`)} · {s.page}
                      </a>
                    </span>
                  ))}.
                </>}
              </p>
            </>
          ) : (
            <p className="muted">{t("sheet.controls.none")}</p>
          )}
          <div className="controls__actions">
            {data.can_generate && (
              <button type="button" className={`button button--small ${data.status === "none" ? "button--primary" : ""}`}
                disabled={generate.isPending} onClick={() => generate.mutate()}>
                {generate.isPending ? <Loader2 size={14} className="spin" aria-hidden /> : <Sparkles size={14} aria-hidden />}{" "}
                {generate.isPending ? t("sheet.controls.asking")
                  : t(data.status === "none" ? "sheet.controls.ask" : "sheet.controls.askAgain")}
              </button>
            )}
            <button type="button" className="button button--small" onClick={startEdit}>
              <Pencil size={14} aria-hidden /> {t(data.status === "none" ? "sheet.controls.write" : "sheet.controls.edit")}
            </button>
          </div>
          {!data.can_generate && data.status === "none" && (
            <p className="muted"><Link to="/parametres/ia">{t("sheet.controls.needKey")}</Link></p>
          )}
          {generate.isError && <ErrorNotice error={generate.error} />}
        </>
      )}
    </section>
  );
}
