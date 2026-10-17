import * as ToggleGroup from "@radix-ui/react-toggle-group";
import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import type { ScanRun } from "../api/client";
import { useChanges, useDuplicates, useStartSync, useStatus, useSyncs } from "../api/queries";
import { GameSheet } from "../components/GameSheet";
import { Empty, ErrorNotice, hintFor, Meter, PageHeader, Spinner } from "../components/ui";
import { getLang, useT } from "../i18n";
import { has } from "../i18n/core";
import { bytes, dateTime } from "../lib/format";

type T = ReturnType<typeof useT>;

// Clés de traduction (préfixe sync.), traduites à l'affichage.
const STATUS_LABEL: Record<ScanRun["status"], string> = {
  running: "sync.status.running",
  completed: "sync.status.completed",
  partial: "sync.status.partial",
  failed: "sync.status.failed",
  interrupted: "sync.status.interrupted",
};

const CHANGE_FILTERS = ["all", "added", "modified", "removed", "restored"];

function duration(run: ScanRun, t: T): string {
  if (!run.finished_at) return "";
  const s = (new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000;
  return s < 60 ? t("sync.run.seconds", { count: Math.max(1, Math.round(s)) }) : t("sync.run.minutes", { count: Math.round(s / 60) });
}

/** Le backend enregistre l'échec sous la forme « code: message ». */
const failureCode = (e: string | null) => (e ?? "").split(":")[0]!.trim();
function failureText(e: string | null, t: T): string {
  if (!e) return t("sync.unknownReason");
  const code = failureCode(e);
  if (e.includes(":") && getLang() !== "fr" && has(`common.error.${code}`)) return t(`common.error.${code}`);
  return e.includes(":") ? e.slice(e.indexOf(":") + 1).trim() : e;
}

export function SyncPage() {
  const t = useT();
  const status = useStatus();
  const syncs = useSyncs();
  const start = useStartSync(() => undefined);
  const dups = useDuplicates();
  const [runId, setRunId] = useState<number | undefined>();
  const [change, setChange] = useState("all");
  const [openId, setOpenId] = useState<number | null>(null);

  const runs = syncs.data ?? [];
  const finished = runs.filter((r) => r.status === "completed" || r.status === "partial");
  useEffect(() => {
    if (runId == null && finished[0]) setRunId(finished[0].id);
  }, [finished, runId]);
  const changes = useChanges(runId, change === "all" ? undefined : change);
  const live = status.data?.sync_running ? status.data.last_run : null;
  const lastFailed = !live && runs[0] && (runs[0].status === "failed" || runs[0].status === "interrupted") ? runs[0] : null;

  return (
    <div className="page">
      <PageHeader
        title={t("sync.title")}
        lead={t("sync.lead")}
      >
        <button type="button" className="button button--primary" onClick={() => start.mutate()} disabled={!!live || start.isPending}>
          <RefreshCw size={16} aria-hidden className={live ? "spin" : ""} />
          {live ? t("sync.running") : t("sync.start")}
        </button>
      </PageHeader>

      {start.isError && <ErrorNotice error={start.error} />}

      {live && (
        <section className="block progress-block" aria-live="polite">
          <p>{t("sync.progress")} <span className="num">{t("sync.progressCount", { done: live.platforms_done, total: live.platforms_total || "…" })}</span></p>
          <Meter value={live.platforms_done} max={live.platforms_total || 1} label={t("sync.progressLabel")} />
        </section>
      )}

      {lastFailed && (
        <div className="notice notice--error" role="alert">
          <div>
            <p className="notice__title">{t("sync.failed.title", { date: dateTime(lastFailed.started_at) })}</p>
            <p>{failureText(lastFailed.error, t)}</p>
            {hintFor(failureCode(lastFailed.error)) && <p className="notice__hint">{hintFor(failureCode(lastFailed.error))}</p>}
            <p className="notice__hint">{t("sync.failed.unchanged")}</p>
          </div>
        </div>
      )}

      <div className="sync-layout">
        <section className="block" aria-labelledby="hist-h">
          <h2 id="hist-h">{t("sync.history.title")}</h2>
          {syncs.isPending && <Spinner label={t("common.loading")} />}
          {runs.length === 0 && !syncs.isPending && <Empty title={t("sync.history.empty")}><p>{t("sync.history.emptyBody")}</p></Empty>}
          <ul className="runs">
            {runs.map((r) => {
              const selectable = r.status === "completed" || r.status === "partial";
              return (
                <li key={r.id}>
                  <button type="button" className={`run ${r.id === runId ? "is-selected" : ""}`} disabled={!selectable} onClick={() => setRunId(r.id)}
                    aria-pressed={r.id === runId}>
                    <span className={`run__status is-${r.status}`}>{t(STATUS_LABEL[r.status])}</span>
                    <span className="run__date">{dateTime(r.started_at)}</span>
                    {selectable && (
                      <span className="run__counts num">
                        {t("sync.run.counts", { added: r.added, modified: r.modified, removed: r.removed })}
                        {r.restored > 0 && t("sync.run.restored", { count: r.restored })}
                        <span className="muted">{t("sync.run.duration", { duration: duration(r, t) })}</span>
                      </span>
                    )}
                    {Object.keys(r.platform_errors).length > 0 && (
                      <span className="run__err">{t("sync.run.unread", { list: Object.keys(r.platform_errors).join(", ") })}</span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>

        <section className="block" aria-labelledby="chg-h">
          <div className="block__head">
            <h2 id="chg-h">{t("sync.changes.title")}</h2>
            <ToggleGroup.Root type="single" className="segmented segmented--text" value={change} onValueChange={(v) => v && setChange(v)} aria-label={t("sync.changes.type")}>
              {CHANGE_FILTERS.map((f) => (
                <ToggleGroup.Item key={f} value={f} className="segmented__item">{t(`sync.filter.${f}`)}</ToggleGroup.Item>
              ))}
            </ToggleGroup.Root>
          </div>
          {changes.isError && <ErrorNotice error={changes.error} />}
          {changes.data && changes.data.items.length === 0 && (
            <Empty title={change === "all" ? t("sync.changes.emptyAll") : t("sync.changes.emptyFiltered")} />
          )}
          {changes.data && changes.data.items.length > 0 && (
            <>
              <ul className="changes">
                {changes.data.items.map((c, i) => (
                  <li key={i}>
                    <span className={`change-tag is-${c.change}`}>{t(`sync.change.${c.change}`)}</span>
                    <button type="button" className="link-button" onClick={() => setOpenId(c.game.id)}>{c.game.filename}</button>
                    <span className="muted">{c.game.platform.directory}</span>
                    <span className="muted num">
                      {c.change === "modified" ? `${bytes(c.old_size)} → ${bytes(c.new_size)}` : bytes(c.new_size ?? c.old_size)}
                    </span>
                  </li>
                ))}
              </ul>
              {changes.data.page.total > changes.data.items.length && (
                <p className="muted">{t("sync.changes.firstOf", { shown: changes.data.items.length, total: changes.data.page.total })}</p>
              )}
            </>
          )}
        </section>
      </div>

      <section className="block" aria-labelledby="dup-h">
        <h2 id="dup-h">{t("sync.dups.title")}</h2>
        <p className="muted block__lead">{t("sync.dups.lead")}</p>
        {dups.data && dups.data.length === 0 && <Empty title={t("sync.dups.empty")} />}
        <ul className="dups">
          {(dups.data ?? []).map((d) => (
            <li key={`${d.platform.id}-${d.normalized_title}`}>
              <p className="dups__head">
                <span className={`change-tag ${d.confidence === "likely" ? "is-modified" : ""}`}>
                  {d.confidence === "likely" ? t("sync.dups.sameSize") : t("sync.dups.sameTitle")}
                </span>
                <span>{d.platform.label ?? d.platform.directory}</span>
              </p>
              <ul className="dups__files">
                {d.items.map((g) => (
                  <li key={g.id}>
                    <button type="button" className="link-button" onClick={() => setOpenId(g.id)}>{g.filename}</button>
                    <span className="muted num">{bytes(g.size)}</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </section>
      <GameSheet id={openId} onClose={() => setOpenId(null)} onOpen={setOpenId} />
    </div>
  );
}
