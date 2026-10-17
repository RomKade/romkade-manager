import { AlertTriangle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import { ApiError } from "../api/client";
import { getLang, t, useLang } from "../i18n";
import { has } from "../i18n/core";

export function PageHeader({ title, children, lead }: { title: string; lead?: ReactNode; children?: ReactNode }) {
  return (
    <header className="page-header">
      <div className="page-header__text">
        <h1>{title}</h1>
        {lead && <p className="page-header__lead">{lead}</p>}
      </div>
      {children && <div className="page-header__actions">{children}</div>}
    </header>
  );
}

/** Conseil associé à un code d'erreur du serveur, dans la langue choisie. */
export function hintFor(code: string): string | undefined {
  return has(`common.hint.${code}`) ? t(`common.hint.${code}`) : undefined;
}

/**
 * Le serveur répond en français ; dans une autre langue, on traduit le message à partir de son code
 * quand on le connaît, sinon on garde le texte du serveur.
 */
export function errorMessage(error: unknown): string {
  const e = error instanceof ApiError ? error : null;
  if (e && getLang() !== "fr" && has(`common.error.${e.code}`)) return t(`common.error.${e.code}`);
  return e?.message ?? (error instanceof Error ? error.message : t("common.unknownError"));
}

export function ErrorNotice({ error, title }: { error: unknown; title?: string }) {
  useLang();
  const e = error instanceof ApiError ? error : null;
  const message = errorMessage(error);
  const hint = e ? hintFor(e.code) : undefined;
  return (
    <div className="notice notice--error" role="alert">
      <AlertTriangle aria-hidden size={18} />
      <div>
        <p className="notice__title">{title ?? message}</p>
        {title && <p>{message}</p>}
        {hint && <p className="notice__hint">{hint}</p>}
      </div>
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <span className="spinner" role="status">
      <Loader2 aria-hidden size={16} className="spin" />
      {label}
    </span>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <p className="empty__title">{title}</p>
      {children && <div className="empty__body">{children}</div>}
    </div>
  );
}

export function Meter({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="meter" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}>
      <div className="meter__fill" style={{ width: `${pct}%` }} />
    </div>
  );
}
