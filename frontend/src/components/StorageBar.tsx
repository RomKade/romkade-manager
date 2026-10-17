import { useState } from "react";

import type { CatalogPlatform } from "../api/client";
import { t as translate, useT } from "../i18n";
import { bytes, gb } from "../lib/format";

const SERIES = 6;

type Segment = { key: string; label: string; bytes: number; color: string; kind: "series" | "other" | "system" | "free" };

/**
 * Occupation de la microSD : les jeux des 6 consoles les plus lourdes (couleurs fixes dans l'ordre),
 * les autres consoles regroupées, l'espace occupé hors ROMs (système, BIOS, images…) et l'espace libre hachuré.
 */
export function buildSegments(platforms: CatalogPlatform[], total: number, free: number): Segment[] {
  const sorted = [...platforms].filter((p) => p.total_bytes > 0).sort((a, b) => b.total_bytes - a.total_bytes);
  const top = sorted.slice(0, SERIES);
  const rest = sorted.slice(SERIES);
  const segs: Segment[] = top.map((p, i) => ({
    key: p.directory, label: p.label ?? p.directory, bytes: p.total_bytes, color: `var(--series-${i + 1})`, kind: "series",
  }));
  const restBytes = rest.reduce((s, p) => s + p.total_bytes, 0);
  if (restBytes > 0) segs.push({ key: "other", label: translate("transfers.storage.others", { count: rest.length }), bytes: restBytes, color: "var(--series-other)", kind: "other" });
  const roms = sorted.reduce((s, p) => s + p.total_bytes, 0);
  const system = Math.max(0, total - free - roms);
  if (system > 0) segs.push({ key: "system", label: translate("transfers.storage.system"), bytes: system, color: "var(--line-strong)", kind: "system" });
  segs.push({ key: "free", label: translate("transfers.storage.free"), bytes: free, color: "transparent", kind: "free" });
  return segs;
}

export function StorageBar({ platforms, total, free }: { platforms: CatalogPlatform[]; total: number; free: number }) {
  const t = useT();
  const segs = buildSegments(platforms, total, free);
  const [hover, setHover] = useState<Segment | null>(null);
  return (
    <figure className="storage">
      <div className="storage__bar" onMouseLeave={() => setHover(null)}>
        {segs.map((s) => (
          <div
            key={s.key}
            className={`storage__seg storage__seg--${s.kind}`}
            style={{ flexGrow: s.bytes, background: s.kind === "free" ? undefined : s.color }}
            onMouseEnter={() => setHover(s)}
            onFocus={() => setHover(s)}
            onBlur={() => setHover(null)}
            tabIndex={0}
            aria-label={t("transfers.storage.segment", { label: s.label, size: bytes(s.bytes) })}
          />
        ))}
      </div>
      <p className="storage__tip num" aria-live="polite">
        {hover ? t("transfers.storage.tip", { label: hover.label, size: gb(hover.bytes), pct: Math.round((hover.bytes / total) * 100) }) : " "}
      </p>
      <figcaption>
        <ul className="legend">
          {segs.map((s) => (
            <li key={s.key}>
              <span className={`legend__swatch legend__swatch--${s.kind}`} style={{ background: s.kind === "free" ? undefined : s.color }} aria-hidden />
              <span>{s.label}</span>
              <span className="muted num">{gb(s.bytes)}</span>
            </li>
          ))}
        </ul>
      </figcaption>
    </figure>
  );
}
