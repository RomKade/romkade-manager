import * as Dialog from "@radix-ui/react-dialog";
import { Archive, ChevronDown, ChevronRight, Download, HardDriveDownload, RotateCcw, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { backupZipUrl, saveFileUrl, type Backup, type Save } from "../api/client";
import { useBackups, useDeviceStatus, useSaveHowto, useSaveMutations, useSaves } from "../api/queries";
import { ConsoleBadge } from "../components/ConsoleBadge";
import { ConsoleIcon } from "../components/ConsoleIcon";
import { Cover } from "../components/Cover";
import { SelectField } from "../components/Filters";
import { PlaySaveButton } from "../components/PlaySaveButton";
import { Empty, ErrorNotice, PageHeader, Spinner } from "../components/ui";
import { regionLabel, useT } from "../i18n";
import { bytes, dateTime } from "../lib/format";
import { saveLabel } from "../lib/saves";

/** Émulateur RetroArch d'après le dossier (saves_RA/Roms/<CONSOLE>/<cœur>/fichier). */
function coreOf(s: Save): string | null {
  const parts = s.rel.split("/");
  return s.source === "retroarch" && parts.length >= 5 ? parts[3]! : null;
}

type Pending =
  | { type: "delete"; save: Save }
  | { type: "restore"; backup: Backup; rel: string; title: string }
  | { type: "deleteBackup"; backup: Backup };

export function SavesPage() {
  const t = useT();
  const [sp, setSp] = useSearchParams();
  const online = useDeviceStatus().data?.connected;
  const saves = useSaves(online !== false);
  const backups = useBackups();
  const m = useSaveMutations();
  const [pending, setPending] = useState<Pending | null>(null);
  const q = sp.get("q") ?? "";
  const platform = sp.get("platform") ?? "";
  const gameId = sp.get("game");

  const list = saves.data?.saves ?? [];
  const platforms = useMemo(() => [...new Set(list.map((s) => s.platform ?? "?"))].sort(), [list]);
  const groups = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const by = new Map<string, { key: string; title: string; platform: string; save: Save; items: Save[] }>();
    for (const s of list) {
      if (platform && (s.platform ?? "?") !== platform) continue;
      if (gameId && String(s.game?.id) !== gameId) continue;
      const title = s.game?.title ?? s.name;
      if (words.length && !words.every((w) => `${title} ${s.name}`.toLowerCase().includes(w))) continue;
      const key = `${s.platform}|${s.game?.id ?? s.name}`;
      const g = by.get(key) ?? { key, title, platform: s.platform ?? "?", save: s, items: [] };
      g.items.push(s);
      by.set(key, g);
    }
    return [...by.values()].sort((a, b) => a.platform.localeCompare(b.platform) || a.title.localeCompare(b.title));
  }, [list, q, platform, gameId]);

  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v) next.set(k, v); else next.delete(k);
    setSp(next, { replace: true });
  };

  const confirm = () => {
    if (!pending) return;
    const done = { onSettled: () => setPending(null) };
    if (pending.type === "delete") m.remove.mutate(pending.save.path, done);
    if (pending.type === "restore") m.restore.mutate({ backup: pending.backup.id, rel: pending.rel }, done);
    if (pending.type === "deleteBackup") m.removeBackup.mutate(pending.backup.id, done);
  };
  const busy = m.remove.isPending || m.restore.isPending || m.removeBackup.isPending;
  const lastError = m.remove.error ?? m.restore.error ?? m.removeBackup.error;

  return (
    <div className="page saves">
      <PageHeader title={t("saves.title")} lead={t("saves.lead")}>
        <button type="button" className="button button--primary" onClick={() => m.backup.mutate(undefined)}
          disabled={m.backup.isPending || !list.length}>
          <HardDriveDownload size={16} aria-hidden /> {m.backup.isPending ? t("saves.backingUp") : t("saves.backupAll")}
        </button>
      </PageHeader>
      {m.backup.isSuccess && (
        <p className="ok-text" role="status">
          {t("saves.backupDone", { count: m.backup.data.files.length, size: bytes(m.backup.data.bytes) })}
        </p>
      )}
      {m.backup.isError && <ErrorNotice error={m.backup.error} />}
      {lastError && <ErrorNotice error={lastError} />}

      <HowTo online={online === true} />

      <section className="block" aria-labelledby="list-h">
        <h2 id="list-h">{t("saves.onConsole")}</h2>
        <div className="saves__filters" role="search">
          <label className="search search--small">
            <Search size={15} aria-hidden />
            <span className="visually-hidden">{t("saves.search")}</span>
            <input type="search" placeholder={t("saves.search")} value={q} onChange={(e) => setParam("q", e.target.value)} />
          </label>
          <SelectField label={t("saves.console")} value={platform || "*"}
            options={[{ value: "*", label: t("saves.allConsoles") }, ...platforms.map((p) => ({ value: p, label: p }))]}
            onChange={(v) => setParam("platform", v === "*" ? "" : v)} />
          {gameId && <button type="button" className="link-button" onClick={() => setParam("game", "")}>{t("saves.allGames")}</button>}
        </div>
        {saves.isPending && online !== false ? (
          <Spinner label={t("saves.scanning")} />
        ) : saves.isError ? (
          <ErrorNotice error={saves.error} title={t("saves.scanError")} />
        ) : online === false && !saves.data ? (
          <p className="muted">{t("saves.offline")}</p>
        ) : groups.length === 0 ? (
          <Empty title={t("saves.none")} />
        ) : (
          <>
            <p className="muted">{t("saves.count", { count: list.length })}{saves.data && ` · ${t("saves.readAt", { at: dateTime(saves.data.scanned_at) })}`}</p>
            <ul className="save-groups">
              {groups.map((g) => (
                <li key={g.key} className="save-group">
                  <div className="save-group__head">
                    {g.save.game ? <Cover game={g.save.game} className="save-group__cover" /> : <ConsoleIcon code={g.platform} className="save-group__cover save-group__cover--console" />}
                    <div>
                      <p className="save-group__title">{g.title}</p>
                      <p className="muted">
                        <ConsoleBadge code={g.save.game?.platform.code ?? g.platform} label={g.save.game?.platform.label} />
                        {g.save.game?.platform.label && ` ${g.save.game.platform.label}`}
                        {g.save.game?.region ? ` · ${regionLabel(g.save.game.region)}` : ""}
                        {!g.save.game && ` · ${t("saves.unmatched")}`}
                      </p>
                    </div>
                  </div>
                  <ul className="save-rows">
                    {g.items.map((s) => (
                      <li key={s.path} className="save-row">
                        <span className={`save-badge save-badge--${s.kind}`}>{saveLabel(t, s)}</span>
                        <span className="muted">{t(`saves.source.${s.source}`)}{coreOf(s) ? ` · ${coreOf(s)}` : ""}</span>
                        <span className="num">{dateTime(s.modified_at)}</span>
                        <span className="num muted">{bytes(s.size)}</span>
                        <span className="save-row__actions">
                          <PlaySaveButton save={s} />
                          <a className="icon-button" href={saveFileUrl(s.path)} download title={t("saves.download")} aria-label={t("saves.download")}>
                            <Download size={15} aria-hidden />
                          </a>
                          <button type="button" className="icon-button" onClick={() => setPending({ type: "delete", save: s })}
                            title={t("saves.delete")} aria-label={t("saves.delete")}>
                            <Trash2 size={15} aria-hidden />
                          </button>
                        </span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="block" aria-labelledby="bk-h">
        <h2 id="bk-h"><Archive size={18} aria-hidden /> {t("saves.onMac")}</h2>
        <p className="muted block__lead">{t("saves.onMacLead")}</p>
        {backups.isPending ? <Spinner label={t("common.loading")} /> : (backups.data ?? []).length === 0 ? (
          <p className="muted">{t("saves.noBackup")}</p>
        ) : (
          <ul className="backup-list">
            {backups.data!.map((b) => (
              <BackupRow key={b.id} backup={b}
                onRestore={(rel, title) => setPending({ type: "restore", backup: b, rel, title })}
                onDelete={() => setPending({ type: "deleteBackup", backup: b })} />
            ))}
          </ul>
        )}
      </section>

      <Dialog.Root open={pending != null} onOpenChange={(o) => !o && !busy && setPending(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="sheet-overlay" />
          <Dialog.Content className="confirm" aria-describedby="confirm-d">
            <Dialog.Title className="confirm__title">
              {pending?.type === "delete" ? t("saves.confirmDelete") : pending?.type === "restore" ? t("saves.confirmRestore") : t("saves.confirmDeleteBackup")}
            </Dialog.Title>
            <p id="confirm-d">
              {pending?.type === "delete" && t("saves.confirmDeleteBody", { name: `${pending.save.game?.title ?? pending.save.name} (${saveLabel(t, pending.save)})` })}
              {pending?.type === "restore" && t("saves.confirmRestoreBody", { name: pending.title, date: dateTime(pending.backup.created_at) })}
              {pending?.type === "deleteBackup" && t("saves.confirmDeleteBackupBody", { date: dateTime(pending.backup.created_at) })}
            </p>
            <div className="confirm__actions">
              <Dialog.Close className="button" disabled={busy}>{t("saves.cancel")}</Dialog.Close>
              <button type="button" className={`button ${pending?.type === "restore" ? "button--primary" : "button--danger"}`} onClick={confirm} disabled={busy}>
                {busy ? t("saves.working") : pending?.type === "restore" ? t("saves.restore") : t("saves.delete")}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

function BackupRow({ backup, onRestore, onDelete }: {
  backup: Backup; onRestore: (rel: string, title: string) => void; onDelete: () => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <li className="backup">
      <div className="backup__head">
        <button type="button" className="link-button backup__toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? <ChevronDown size={15} aria-hidden /> : <ChevronRight size={15} aria-hidden />}
          <strong>{dateTime(backup.created_at)}</strong>
        </button>
        {backup.auto && <span className="tag">{t("saves.autoCopy")}</span>}
        <span className="muted">{t("saves.files", { count: backup.files.length })} · {bytes(backup.bytes)}</span>
        <span className="save-row__actions">
          <a className="icon-button" href={backupZipUrl(backup.id)} download title={t("saves.downloadZip")} aria-label={t("saves.downloadZip")}>
            <Download size={15} aria-hidden />
          </a>
          <button type="button" className="icon-button" onClick={onDelete} title={t("saves.deleteBackup")} aria-label={t("saves.deleteBackup")}>
            <Trash2 size={15} aria-hidden />
          </button>
        </span>
      </div>
      {open && (
        <ul className="save-rows">
          {backup.files.map((f) => {
            const title = f.game_title ?? f.rel.split("/").pop()!;
            return (
              <li key={f.rel} className="save-row">
                <span className={`save-badge save-badge--${f.kind ?? "sram"}`}>{saveLabel(t, { kind: f.kind ?? "sram", slot: f.slot })}</span>
                <span className="save-row__name">{title}{f.platform ? ` · ${f.platform}` : ""}</span>
                <span className="num">{f.modified_at ? dateTime(f.modified_at) : ""}</span>
                <span className="num muted">{bytes(f.size)}</span>
                <span className="save-row__actions">
                  <button type="button" className="button button--small" onClick={() => onRestore(f.rel, title)}>
                    <RotateCcw size={14} aria-hidden /> {t("saves.restore")}
                  </button>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}

function HowTo({ online }: { online: boolean }) {
  const t = useT();
  const keys = useSaveHowto(online);
  return (
    <section className="block howto" aria-labelledby="howto-h">
      <h2 id="howto-h">{t("saves.howto.title")}</h2>
      <div className="howto__cols">
        <div>
          <h3>{t("saves.kind.sram")}</h3>
          <p>{t("saves.howto.sram")}</p>
        </div>
        <div>
          <h3>{t("saves.howto.stateTitle")}</h3>
          <p>{t("saves.howto.state")}</p>
          {keys.data && (
            <ul className="hotkeys">
              {keys.data.filter((k) => k.action !== "menu").map((k) => (
                <li key={k.action}>
                  <span className="hotkeys__combo">{k.combo.map((c, i) => <span key={i}>{i > 0 && " + "}<kbd>{c}</kbd></span>)}</span>
                  <span>{t(`saves.howto.key.${k.action}`)}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="muted">{t("saves.howto.auto")}</p>
        </div>
        <div>
          <h3>{t("saves.howto.otherTitle")}</h3>
          <p>{t("saves.howto.other")}</p>
        </div>
      </div>
    </section>
  );
}
