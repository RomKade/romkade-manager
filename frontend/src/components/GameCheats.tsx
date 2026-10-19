import { useMutation } from "@tanstack/react-query";
import { Download, ExternalLink, KeyRound, Loader2, Send } from "lucide-react";
import { useState } from "react";

import { api } from "../api/client";
import { useDownloadCheats, useGameCheats } from "../api/queries";
import { useT } from "../i18n";
import { ErrorNotice } from "./ui";

const SHOWN = 8;

/** Fiche du jeu : codes de triche de la base de RetroArch (sans IA), variante au choix (région, Game Genie…), et
 * copie du fichier sur la console pour les activer en jeu. */
export function GameCheatsSection({ id }: { id: number }) {
  const t = useT();
  const q = useGameCheats(id);
  const download = useDownloadCheats();
  const [pick, setPick] = useState(0);
  const [all, setAll] = useState(false);
  const install = useMutation({ mutationFn: (name: string) => api.installCheats(id, name) });
  const data = q.data;
  if (!data) return null;
  const file = data.files[Math.min(pick, data.files.length - 1)];

  return (
    <section className="sheet__section cheats" aria-labelledby="cheats-h">
      <h2 id="cheats-h"><KeyRound size={18} aria-hidden /> {t("sheet.cheats.title")}</h2>
      {!data.available ? (
        <div className="cheats__empty">
          <p className="muted">{t("sheet.cheats.notDownloaded")}</p>
          <button type="button" className="button button--small" disabled={download.isPending} onClick={() => download.mutate()}>
            {download.isPending ? <Loader2 size={14} aria-hidden className="spin" /> : <Download size={14} aria-hidden />}{" "}
            {download.isPending ? t("sheet.cheats.downloading") : t("sheet.cheats.download")}
          </button>
          {download.isError && <ErrorNotice error={download.error} />}
        </div>
      ) : !file ? (
        <p className="muted">{t("sheet.cheats.none")}</p>
      ) : (
        <>
          {data.files.length > 1 && (
            <label className="field cheats__variant">
              <span className="field__label">{t("sheet.cheats.variant")}</span>
              <select value={pick} onChange={(e) => { setPick(Number(e.target.value)); setAll(false); install.reset(); }}>
                {data.files.map((f, i) => (
                  <option key={f.name} value={i}>{t("sheet.cheats.option", { label: f.label, count: f.count })}</option>
                ))}
              </select>
            </label>
          )}
          <p className="muted small">{t("sheet.cheats.versionNote")}</p>
          <ul className="cheats__list">
            {(all ? file.cheats : file.cheats.slice(0, SHOWN)).map((c, i) => (
              <li key={i}><span>{c.desc}</span> <code>{c.code}</code></li>
            ))}
          </ul>
          {file.cheats.length > SHOWN && (
            <button type="button" className="link-button" onClick={() => setAll((v) => !v)}>
              {all ? t("sheet.cheats.less") : t("sheet.cheats.more", { count: file.cheats.length })}
            </button>
          )}
          {data.can_install && (
            <div className="form__actions">
              <button type="button" className="button button--small" disabled={install.isPending} onClick={() => install.mutate(file.name)}>
                {install.isPending ? <Loader2 size={14} aria-hidden className="spin" /> : <Send size={14} aria-hidden />}{" "}
                {t("sheet.cheats.install")}
              </button>
            </div>
          )}
          {install.isSuccess && <p className="text-ok small" role="status">{t("sheet.cheats.installed")}</p>}
          {install.isError && <ErrorNotice error={install.error} />}
          <p className="muted small">{t("sheet.cheats.howTo")}</p>
        </>
      )}
      <p className="muted small">
        <a href={data.source_url} target="_blank" rel="noreferrer noopener">
          {t("sheet.cheats.source", { license: data.license })} <ExternalLink size={11} aria-hidden />
        </a>
      </p>
    </section>
  );
}
