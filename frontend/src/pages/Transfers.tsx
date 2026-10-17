import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileUp, RotateCcw, Trash2, Upload as UploadIcon, X } from "lucide-react";
import { useCallback, useMemo, useRef, useState, type DragEvent } from "react";

import { api, ApiError, uploadFile, type PlanItem, type StartItem, type Transfer } from "../api/client";
import { isActive, usePlatforms, useTransfers, useUploads } from "../api/queries";
import { SelectField } from "../components/Filters";
import { errorMessage, ErrorNotice, hintFor, Meter, PageHeader } from "../components/ui";
import { getLang, useT } from "../i18n";
import { has } from "../i18n/core";
import { bytes, dateTime, gb } from "../lib/format";

type Conflict = StartItem["on_conflict"];
type Sending = { key: string; name: string; loaded: number; total: number; error?: string };

type T = ReturnType<typeof useT>;

// Clés de traduction (préfixe transfers.), traduites à l'affichage.
const CONFLICT_OPTIONS = ["skip", "rename", "overwrite"];

const STATUS_LABEL: Record<Transfer["status"], string> = {
  queued: "transfers.status.queued",
  running: "transfers.status.running",
  verifying: "transfers.status.verifying",
  completed: "transfers.status.completed",
  skipped: "transfers.status.skipped",
  failed: "transfers.status.failed",
  cancelled: "transfers.status.cancelled",
  interrupted: "transfers.status.interrupted",
};

function eta(s: number | null | undefined, t: T): string {
  if (!s || !isFinite(s)) return "";
  if (s < 60) return t("transfers.xfer.etaSeconds", { count: Math.ceil(s) });
  return t("transfers.xfer.etaMinutes", { count: Math.ceil(s / 60) });
}

/** Message du serveur, traduit hors français quand son code est connu. */
function codeText(code: unknown, message: string, t: T): string {
  if (typeof code === "string" && getLang() !== "fr" && has(`common.error.${code}`)) return t(`common.error.${code}`);
  return message;
}

// Les échecs sont enregistrés sous la forme « code_technique: message » ; les autres messages sont du texte simple.
const CODE_PREFIX = /^([a-z_]+): /;
const errCode = (e: string | null) => CODE_PREFIX.exec(e ?? "")?.[1] ?? "";
const errText = (e: string | null, t: T) => codeText(errCode(e), (e ?? "").replace(CODE_PREFIX, ""), t);

export function TransfersPage() {
  const t = useT();
  const qc = useQueryClient();
  const uploads = useUploads();
  const transfers = useTransfers();
  const platforms = usePlatforms();
  const [sending, setSending] = useState<Sending[]>([]);
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [choices, setChoices] = useState<Record<string, Conflict>>({});
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  // Les fichiers en zone d'attente qui ne sont pas déjà en cours de transfert.
  const busy = new Set((transfers.data ?? []).filter(isActive).map((x) => x.upload_id));
  const staged = (uploads.data ?? []).filter((u) => !busy.has(u.id));
  const planReq = staged.map((u) => ({ upload_id: u.id, platform: targets[u.id] ?? null }));
  const plan = useQuery({
    queryKey: ["plan", planReq],
    queryFn: () => api.plan(planReq),
    enabled: planReq.length > 0,
    retry: false,
  });

  const sendFiles = useCallback(async (files: File[]) => {
    const items = files.map((f, i) => ({ key: `${Date.now()}-${i}-${f.name}`, name: f.name, loaded: 0, total: f.size, file: f }));
    setSending((s) => [...s, ...items.map(({ file: _f, ...rest }) => rest)]);
    // Deux envois à la fois : le disque du Mac suit sans problème, et l'interface reste réactive.
    const queue = [...items];
    const worker = async () => {
      for (let it = queue.shift(); it; it = queue.shift()) {
        const cur = it;
        try {
          await uploadFile(cur.file, (loaded, total) =>
            setSending((s) => s.map((x) => (x.key === cur.key ? { ...x, loaded, total } : x))));
          setSending((s) => s.filter((x) => x.key !== cur.key));
          qc.invalidateQueries({ queryKey: ["uploads"] });
        } catch (e) {
          const msg = e instanceof ApiError ? errorMessage(e) : t("transfers.sending.failed");
          setSending((s) => s.map((x) => (x.key === cur.key ? { ...x, error: msg } : x)));
        }
      }
    };
    await Promise.all([worker(), worker()]);
  }, [qc, t]);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = [...e.dataTransfer.files].filter((f) => f.size > 0 || f.type);
    if (files.length) void sendFiles(files);
  };

  const remove = useMutation({ mutationFn: api.deleteUpload, onSuccess: () => qc.invalidateQueries({ queryKey: ["uploads"] }) });
  const start = useMutation({
    mutationFn: ({ items, confirm }: { items: StartItem[]; confirm: boolean }) => api.startTransfers(items, confirm),
    onSuccess: () => {
      setConfirmOpen(false);
      setTargets({});
      setChoices({});
      qc.invalidateQueries({ queryKey: ["transfers"] });
      qc.invalidateQueries({ queryKey: ["uploads"] });
    },
  });

  const items = plan.data?.items ?? [];
  const startItems: StartItem[] = items
    .filter((i) => i.platform && !i.error)
    .map((i) => ({ upload_id: i.upload_id, platform: i.platform!, on_conflict: choices[i.upload_id] ?? "skip" }));
  const overwrites = items.filter((i) => i.conflict && choices[i.upload_id] === "overwrite");
  const skipped = items.filter((i) => i.conflict && (choices[i.upload_id] ?? "skip") === "skip");
  const copyBytes = items.filter((i) => !i.error && !skipped.includes(i)).reduce((s, i) => s + i.size, 0);
  const blocking = items.filter((i) => i.error).length;

  const platformOptions = useMemo(
    () => (platforms.data ?? [])
      .filter((p) => p.kind !== "apps" && p.kind !== "ports")
      .map((p) => ({ value: p.directory, label: `${p.label ?? p.directory} (${p.directory})` }))
      .sort((a, b) => a.label.localeCompare(b.label, "fr")),
    [platforms.data],
  );

  const launch = () => (overwrites.length ? setConfirmOpen(true) : start.mutate({ items: startItems, confirm: false }));
  const all = transfers.data ?? [];
  const active = all.filter(isActive);
  const done = all.filter((x) => !isActive(x));

  return (
    <div className="page transfers" onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
      <PageHeader title={t("transfers.title")} lead={t("transfers.lead")} />

      <section
        className={`dropzone ${dragging ? "is-over" : ""}`}
        aria-labelledby="drop-h"
      >
        <FileUp size={28} aria-hidden strokeWidth={1.5} />
        <h2 id="drop-h">{t("transfers.drop.title")}</h2>
        <p className="muted">{t("transfers.drop.lead")}</p>
        <button type="button" className="button" onClick={() => input.current?.click()}>
          <UploadIcon size={16} aria-hidden /> {t("transfers.drop.choose")}
        </button>
        <input ref={input} type="file" multiple hidden onChange={(e) => { const f = [...(e.target.files ?? [])]; e.target.value = ""; if (f.length) void sendFiles(f); }} />
      </section>

      {sending.length > 0 && (
        <section className="block" aria-labelledby="send-h" aria-live="polite">
          <h2 id="send-h">{t("transfers.sending.title")}</h2>
          <ul className="xfer-list">
            {sending.map((s) => (
              <li key={s.key} className="xfer">
                <div className="xfer__main">
                  <span className="xfer__name break">{s.name}</span>
                  {s.error ? <span className="text-error">{s.error}</span> : <span className="muted num">{t("transfers.percent", { pct: Math.round((s.loaded / (s.total || 1)) * 100) })}</span>}
                </div>
                {!s.error && <Meter value={s.loaded} max={s.total || 1} label={t("transfers.sending.meter", { name: s.name })} />}
                {s.error && (
                  <button type="button" className="icon-button" aria-label={t("transfers.remove")} onClick={() => setSending((x) => x.filter((y) => y.key !== s.key))}>
                    <X size={16} aria-hidden />
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {staged.length > 0 && (
        <section className="block" aria-labelledby="plan-h">
          <div className="block__head">
            <h2 id="plan-h">{t("transfers.plan.title")}</h2>
            {plan.data && (
              <p className={`num ${plan.data.fits === false ? "text-error" : "muted"}`}>
                {copyBytes ? t("transfers.plan.toCopy", { size: bytes(copyBytes) }) : t("transfers.plan.nothing")}, {plan.data.free_bytes == null ? t("transfers.plan.freeUnknown") : t("transfers.plan.free", { free: gb(plan.data.free_bytes) })}
              </p>
            )}
          </div>
          {plan.isError && <ErrorNotice error={plan.error} title={t("transfers.plan.error")} />}
          {plan.data?.fits === false && (
            <div className="notice notice--error" role="alert">
              <AlertTriangle size={18} aria-hidden />
              <div>
                <p className="notice__title">{t("transfers.plan.noSpace")}</p>
                <p>{t("transfers.plan.noSpaceBody", { needed: bytes(copyBytes + plan.data.margin_bytes), margin: bytes(plan.data.margin_bytes) })}</p>
              </div>
            </div>
          )}
          <ul className="plan-list">
            {(plan.data ? items : staged.map((u) => ({ upload_id: u.id, filename: u.filename, size: u.size } as PlanItem))).map((it) => (
              <PlanRow
                key={it.upload_id}
                item={it}
                pending={!plan.data}
                platformOptions={platformOptions}
                choice={choices[it.upload_id] ?? "skip"}
                onPlatform={(p) => setTargets((x) => ({ ...x, [it.upload_id]: p }))}
                onChoice={(c) => setChoices((x) => ({ ...x, [it.upload_id]: c }))}
                onRemove={() => remove.mutate(it.upload_id)}
              />
            ))}
          </ul>
          <div className="plan-actions">
            <button type="button" className="button button--primary" onClick={launch}
              disabled={!plan.data?.ready || start.isPending || startItems.length === 0 || startItems.length === skipped.length}>
              {t("transfers.plan.start")}
            </button>
            <p className="muted">
              {blocking > 0 ? t("transfers.plan.blocking", { count: blocking }) :
                skipped.length > 0 ? t("transfers.plan.skipped", { count: skipped.length }) : ""}
            </p>
          </div>
          {start.isError && <ErrorNotice error={start.error} />}
        </section>
      )}

      {active.length > 0 && (
        <section className="block" aria-labelledby="active-h" aria-live="polite">
          <h2 id="active-h">{t("transfers.active.title")}</h2>
          <ul className="xfer-list">{active.map((x) => <TransferRow key={x.id} t={x} />)}</ul>
        </section>
      )}

      <section className="block" aria-labelledby="hist-h">
        <h2 id="hist-h">{t("transfers.history.title")}</h2>
        {done.length === 0 ? <p className="muted">{t("transfers.history.empty")}</p> : (
          <ul className="xfer-list">{done.map((x) => <TransferRow key={x.id} t={x} />)}</ul>
        )}
      </section>

      <Dialog.Root open={confirmOpen} onOpenChange={setConfirmOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="sheet-overlay" />
          <Dialog.Content className="confirm">
            <Dialog.Title className="confirm__title">{t("transfers.confirm.title", { count: overwrites.length })}</Dialog.Title>
            <Dialog.Description className="muted">
              {t("transfers.confirm.bodyBefore")} <code>.agm-backups</code> {t("transfers.confirm.bodyAfter")}
            </Dialog.Description>
            <ul className="confirm__list">
              {overwrites.map((o) => (
                <li key={o.upload_id}>
                  <span className="break">{o.conflict!.existing as string}</span>
                  <span className="muted num">{t("transfers.confirm.replaced", { old: bytes(o.conflict!.existing_size as number), new: bytes(o.size) })}</span>
                </li>
              ))}
            </ul>
            <div className="confirm__actions">
              <Dialog.Close className="button">{t("transfers.cancel")}</Dialog.Close>
              <button type="button" className="button button--primary" disabled={start.isPending}
                onClick={() => start.mutate({ items: startItems, confirm: true })}>
                {t("transfers.confirm.go")}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

function PlanRow({ item, pending, platformOptions, choice, onPlatform, onChoice, onRemove }: {
  item: PlanItem; pending: boolean; platformOptions: { value: string; label: string }[]; choice: Conflict;
  onPlatform: (p: string) => void; onChoice: (c: Conflict) => void; onRemove: () => void;
}) {
  const t = useT();
  const preferred = new Set(item.platform_choices ?? []);
  const opts = [
    ...platformOptions.filter((o) => preferred.has(o.value)),
    ...platformOptions.filter((o) => !preferred.has(o.value)),
  ];
  const conflict = item.conflict as { existing: string; existing_size: number | null; same_size: boolean; case_only?: boolean } | null;
  return (
    <li className={`plan-row ${item.error ? "has-error" : ""}`}>
      <div className="plan-row__file">
        <span className="plan-row__name break">{item.filename}</span>
        <span className="muted num">{bytes(item.size)}</span>
      </div>
      <div className="plan-row__dest">
        {pending ? <span className="muted">{t("transfers.row.analysing")}</span> : (
          <SelectField label={t("transfers.row.dest", { name: item.filename })} value={item.platform ?? undefined}
            placeholder={t("transfers.row.destPlaceholder")} options={opts} onChange={onPlatform} />
        )}
      </div>
      <div className="plan-row__status">
        {item.error && <p className="text-error">{codeText(item.error.code, item.error.message as string, t)}</p>}
        {conflict && (
          <>
            <p className="warn-text">
              {conflict.case_only ? t("transfers.row.caseOnly", { name: conflict.existing }) : t("transfers.row.present")}
              {conflict.same_size ? t("transfers.row.sameSize") : t("transfers.row.diffSize", { size: bytes(conflict.existing_size) })}
            </p>
            <SelectField label={t("transfers.row.choice", { name: item.filename })} value={choice}
              options={CONFLICT_OPTIONS.map((value) => ({ value, label: t(`transfers.conflict.${value}`) }))} onChange={(v) => onChoice(v as Conflict)} />
          </>
        )}
        {(item.warnings ?? []).map((w, i) => (
          <p key={i} className="warn-text">
            {codeText(w.code, w.message as string, t)}
            {Array.isArray(w.files) && `: ${(w.files as string[]).join(", ")}`}
          </p>
        ))}
        {!pending && !item.error && !conflict && (item.warnings ?? []).length === 0 && (
          <p className="ok-text"><CheckCircle2 size={15} aria-hidden /> {t("transfers.row.ready")}</p>
        )}
      </div>
      <button type="button" className="icon-button" aria-label={t("transfers.row.remove", { name: item.filename })} onClick={onRemove}>
        <Trash2 size={16} aria-hidden />
      </button>
    </li>
  );
}

function TransferRow({ t: x }: { t: Transfer }) {
  const t = useT();
  const qc = useQueryClient();
  const cancel = useMutation({ mutationFn: () => api.cancelTransfer(x.id), onSettled: () => qc.invalidateQueries({ queryKey: ["transfers"] }) });
  const retry = useMutation({ mutationFn: () => api.retryTransfer(x.id), onSettled: () => qc.invalidateQueries({ queryKey: ["transfers"] }) });
  const running = x.status === "running" || x.status === "verifying";
  const name = x.final_filename && x.final_filename !== x.filename ? `${x.filename} → ${x.final_filename}` : x.filename;
  const hint = x.status === "failed" ? hintFor(errCode(x.error)) : undefined;
  return (
    <li className={`xfer is-${x.status}`}>
      <div className="xfer__main">
        <span className={`xfer__status is-${x.status}`}>{t(STATUS_LABEL[x.status])}</span>
        <span className="xfer__name break">{name}</span>
        <span className="muted">{x.platform_dir}</span>
        <span className="muted num">{bytes(x.size)}</span>
      </div>
      {running && (
        <>
          <Meter value={x.status === "verifying" ? x.size : x.bytes_done} max={x.size} label={t("transfers.xfer.meter", { name: x.filename })} />
          <p className="xfer__detail muted num">
            {x.status === "verifying" ? t("transfers.xfer.verifying") :
              `${t("transfers.percent", { pct: Math.round((x.bytes_done / x.size) * 100) })}${x.speed_bps ? `, ${bytes(x.speed_bps)}/s` : ""}${x.eta_seconds ? `, ${eta(x.eta_seconds, t)}` : ""}`}
          </p>
        </>
      )}
      {x.status === "completed" && (
        <p className="xfer__detail muted">
          {t(x.verify_method === "sha256" ? "transfers.xfer.verifiedSha" : "transfers.xfer.verifiedSize", { date: dateTime(x.finished_at) })}
          {x.backup_path && <>. {t("transfers.xfer.backup")} <code className="break">{x.backup_path}</code></>}
        </p>
      )}
      {(x.status === "failed" || x.status === "cancelled" || x.status === "interrupted" || x.status === "skipped") && x.error && (
        <p className={`xfer__detail ${x.status === "failed" ? "text-error" : "muted"}`}>{errText(x.error, t)}{hint && ` ${hint}`}</p>
      )}
      <div className="xfer__actions">
        {(x.status === "queued" || running) && (
          <button type="button" className="button" onClick={() => cancel.mutate()} disabled={cancel.isPending}>{t("transfers.cancel")}</button>
        )}
        {x.retryable && (
          <button type="button" className="button" onClick={() => retry.mutate()} disabled={retry.isPending}>
            <RotateCcw size={15} aria-hidden /> {t("transfers.retry")}
          </button>
        )}
      </div>
      {retry.isError && <ErrorNotice error={retry.error} />}
    </li>
  );
}
