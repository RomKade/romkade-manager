import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpenText, Download, ExternalLink, KeyRound, Loader2, RefreshCw, Search, Square } from "lucide-react";
import { useState } from "react";

import { api, type GameKnowledge, type KnowledgeHit } from "../api/client";
import { useCheatsStatus, useDownloadCheats, useKnowledge, useKnowledgeMutations, useQuickSearch } from "../api/queries";
import { useT } from "../i18n";
import { useDebounced } from "../lib/hooks";
import { ErrorNotice, Meter, Spinner } from "./ui";

/**
 * Paramètres > Connaissances : pages Wikipédia et StrategyWiki de chaque jeu, récupérées sans IA, que
 * l'assistant lit pour répondre (RAG). Couverture, récupération de tous les jeux en attente, option automatique
 * après synchronisation, et test sur un jeu (récupérer, puis voir les passages trouvés pour une question).
 */
export function KnowledgePanel() {
  const t = useT();
  const q = useKnowledge();
  const { start, stop, auto } = useKnowledgeMutations();
  const st = q.data;
  const job = st?.job;
  return (
    <section className="block knowledge" aria-labelledby="kn-h">
      <div className="block__head">
        <h2 id="kn-h"><BookOpenText size={18} aria-hidden /> {t("settings.kn.title")}</h2>
        <span className="tag tag--ok">{t("settings.noAi")}</span>
      </div>
      <p className="muted block__lead">{t("settings.kn.lead")}</p>
      {q.isPending ? <Spinner label={t("common.loading")} /> : q.isError ? <ErrorNotice error={q.error} /> : st && (
        <>
          <Meter value={st.found} max={Math.max(st.games, 1)} label={t("settings.kn.coverage", { found: st.found, total: st.games })} />
          <p>
            {t("settings.kn.coverage", { found: st.found, total: st.games })}
            <span className="muted"> · {t("settings.kn.details", { notFound: st.not_found, pending: st.pending, chunks: st.chunks })}</span>
          </p>
          {job?.running ? (
            <div className="knowledge__job">
              <p className="desc-run" role="status">
                <Loader2 size={16} aria-hidden className="spin" />{" "}
                {job.stopping ? t("settings.kn.stopping") : job.total === 0 ? t("settings.kn.preparing")
                  : t("settings.kn.running", { done: job.done, total: job.total, found: job.found,
                      minutes: Math.max(1, Math.round((job.total - job.done) * 10 / 60)) })}
              </p>
              {job.total > 0 && <Meter value={job.done} max={job.total} label={t("settings.kn.progress")} />}
              {job.current && <p className="muted small">{t("settings.kn.current", { title: job.current })}</p>}
              <p className="muted small">{t("settings.kn.background")}</p>
              <div className="form__actions">
                <button type="button" className="button button--small" disabled={job.stopping || stop.isPending} onClick={() => stop.mutate()}>
                  <Square size={14} aria-hidden /> {t("settings.kn.stop")}
                </button>
              </div>
            </div>
          ) : (st.pending > 0 || st.games > 0) && (
            <div className="form__actions">
              {st.pending > 0 && (
                <button type="button" className="button button--primary" disabled={start.isPending} onClick={() => start.mutate(false)}>
                  <Download size={16} aria-hidden /> {t("settings.kn.start", { count: st.pending })}
                </button>
              )}
              {st.games > st.pending && (
                <button type="button" className="button button--small" disabled={start.isPending} onClick={() => start.mutate(true)}
                  title={t("settings.kn.refreshHint")}>
                  <RefreshCw size={14} aria-hidden /> {t("settings.kn.refresh", { count: st.games, minutes: Math.max(1, Math.round(st.games * 10 / 60)) })}
                </button>
              )}
            </div>
          )}
          <label className="toggle-inline">
            <input type="checkbox" checked={st.auto_after_sync} disabled={auto.isPending}
              onChange={(e) => auto.mutate(e.target.checked)} />
            {t("settings.kn.auto")}
          </label>
          <p className="muted small">{t("settings.kn.sources", { license: st.license })}</p>
          {((start.isError && (start.error as { code?: string }).code !== "knowledge_running") || stop.isError) &&
            <ErrorNotice error={start.error ?? stop.error} />}
          <KnowledgeTest />
        </>
      )}
    </section>
  );
}

/** Un jeu : récupérer ses connaissances tout de suite, voir les pages trouvées, puis tester une question. */
function KnowledgeTest() {
  const t = useT();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<{ id: number; title: string } | null>(null);
  const [info, setInfo] = useState<GameKnowledge | null>(null);
  const [question, setQuestion] = useState("");
  const [hits, setHits] = useState<KnowledgeHit[] | null>(null);
  const results = useQuickSearch(useDebounced(text, 200));
  const load = useMutation({ mutationFn: api.gameKnowledge, onSuccess: setInfo });
  const fetch = useMutation({
    mutationFn: api.fetchGameKnowledge,
    onSuccess: (d) => { setInfo(d); qc.invalidateQueries({ queryKey: ["knowledge"] }); },
  });
  const ask = useMutation({ mutationFn: (q: string) => api.searchGameKnowledge(picked!.id, q), onSuccess: setHits });
  const pick = (id: number, title: string) => {
    setPicked({ id, title });
    setText("");
    setHits(null);
    setInfo(null);
    load.mutate(id);
  };

  return (
    <div className="knowledge__test">
      <h3>{t("settings.kn.testTitle")}</h3>
      <p className="muted">{t("settings.kn.testLead")}</p>
      <label className="field knowledge__search">
        <span className="field__label">{t("settings.kn.pick")}</span>
        <input type="search" value={text} placeholder={t("settings.kn.pickPlaceholder")} onChange={(e) => setText(e.target.value)} />
      </label>
      {text.trim() && (results.data?.items ?? []).length > 0 && (
        <ul className="knowledge__results">
          {results.data!.items.slice(0, 6).map((g) => (
            <li key={g.id}>
              <button type="button" className="link-button" onClick={() => pick(g.id, g.title)}>
                {g.title} <span className="muted">· {g.platform.label ?? g.platform.directory}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {picked && (
        <div className="knowledge__game">
          <p><strong>{picked.title}</strong>{info && <span className="muted"> · {t(`settings.kn.status.${info.status}`)}</span>}</p>
          <div className="form__actions">
            <button type="button" className="button button--small" disabled={fetch.isPending} onClick={() => fetch.mutate(picked.id)}>
              {fetch.isPending ? <Loader2 size={14} aria-hidden className="spin" /> : <Download size={14} aria-hidden />}{" "}
              {fetch.isPending ? t("settings.kn.fetching") : t(info?.status === "none" ? "settings.kn.fetch" : "settings.kn.refetch")}
            </button>
          </div>
          {(fetch.isError || load.isError) && <ErrorNotice error={fetch.error ?? load.error} />}
          {info && info.sources.length > 0 && (
            <ul className="knowledge__sources">
              {info.sources.map((s) => (
                <li key={s.url}>
                  <a href={s.url} target="_blank" rel="noreferrer noopener">
                    {t(`settings.kn.source.${s.source}`)} ({s.lang}) · {s.page} <ExternalLink size={12} aria-hidden />
                  </a>
                  <span className="muted"> · {t("settings.kn.passages", { count: s.chunks })}</span>
                </li>
              ))}
            </ul>
          )}
          {info?.status === "found" && (
            <form className="knowledge__ask" onSubmit={(e) => { e.preventDefault(); ask.mutate(question); }}>
              <label className="field">
                <span className="field__label">{t("settings.kn.question")}</span>
                <input value={question} maxLength={300} placeholder={t("settings.kn.questionPlaceholder")}
                  onChange={(e) => setQuestion(e.target.value)} />
              </label>
              <button type="submit" className="button button--small" disabled={ask.isPending}>
                <Search size={14} aria-hidden /> {t("settings.kn.ask")}
              </button>
            </form>
          )}
          {hits && (
            <ol className="knowledge__hits">
              {hits.map((h, i) => (
                <li key={i}>
                  <p className="knowledge__hit-head">
                    <strong>{h.section}</strong>{" "}
                    <a href={h.url} target="_blank" rel="noreferrer noopener" className="muted">
                      {t(`settings.kn.source.${h.source}`)} · {h.license}
                    </a>
                  </p>
                  <p className="muted">{h.excerpt}…</p>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}

/** Codes de triche de RetroArch : paquet téléchargé à la demande (sans IA), puis mis à jour quand on veut. */
export function CheatsPanel() {
  const t = useT();
  const q = useCheatsStatus();
  const download = useDownloadCheats();
  const st = q.data;
  return (
    <section className="block knowledge" aria-labelledby="ch-h">
      <div className="block__head">
        <h2 id="ch-h"><KeyRound size={18} aria-hidden /> {t("settings.ch.title")}</h2>
        <span className="tag tag--ok">{t("settings.noAi")}</span>
      </div>
      <p className="muted block__lead">{t("settings.ch.lead")}</p>
      {q.isPending ? <Spinner label={t("common.loading")} /> : q.isError ? <ErrorNotice error={q.error} /> : st && (
        <>
          <p>{st.available && st.updated_at
            ? t("settings.ch.status", { files: st.files.toLocaleString(), date: new Date(st.updated_at).toLocaleDateString() })
            : t("settings.ch.none")}</p>
          <div className="form__actions">
            <button type="button" className={`button ${st.available ? "button--small" : "button--primary"}`}
              disabled={download.isPending} onClick={() => download.mutate()}>
              {download.isPending ? <Loader2 size={16} aria-hidden className="spin" /> : <Download size={16} aria-hidden />}{" "}
              {download.isPending ? t("settings.ch.downloading") : t(st.available ? "settings.ch.update" : "settings.ch.download")}
            </button>
          </div>
          {download.isError && <ErrorNotice error={download.error} />}
          <p className="muted small">
            <a href={st.source_url} target="_blank" rel="noreferrer noopener">libretro-database · {st.license} <ExternalLink size={11} aria-hidden /></a>
          </p>
        </>
      )}
    </section>
  );
}
