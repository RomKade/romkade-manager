import { locale, t } from "../i18n";

// Formats recréés quand la langue change (le cache est indexé par locale).
const cache = new Map<string, unknown>();
function fmt<T>(kind: string, make: (loc: string) => T): T {
  const key = `${kind}|${locale()}`;
  if (!cache.has(key)) cache.set(key, make(locale()));
  return cache.get(key) as T;
}
const nf = () => fmt("n", (l) => new Intl.NumberFormat(l));
const nf1 = () => fmt("n1", (l) => new Intl.NumberFormat(l, { maximumFractionDigits: 1, minimumFractionDigits: 1 }));
const dateFmt = () => fmt("d", (l) => new Intl.DateTimeFormat(l, { day: "numeric", month: "short", year: "numeric" }));
const timeFmt = () => fmt("t", (l) => new Intl.DateTimeFormat(l, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }));
const rtf = () => fmt("r", (l) => new Intl.RelativeTimeFormat(l, { numeric: "auto" }));

export const count = (n: number) => nf().format(n);

export function bytes(n: number | null | undefined): string {
  if (n == null) return t("common.value.unknownF");
  if (n < 1024) return `${n} ${t("common.unit.b")}`;
  const units = ["kb", "mb", "gb", "tb"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v < 10 ? nf1().format(v) : nf().format(Math.round(v))} ${t(`common.unit.${units[i]}`)}`;
}

/** Tailles de carte en Go décimaux, comme l'affichent les fabricants et le rapport de synchronisation. */
export function gb(n: number | null | undefined): string {
  return n == null ? t("common.value.unknownM") : `${nf1().format(n / 1e9)} ${t("common.unit.gb")}`;
}

export const date = (iso: string | null | undefined) => (iso ? dateFmt().format(new Date(iso)) : t("common.value.unknownF"));
export const dateTime = (iso: string | null | undefined) => (iso ? timeFmt().format(new Date(iso)) : t("common.value.never"));

export function ago(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return t("common.value.never");
  const s = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(s);
  if (abs < 60) return t("common.value.justNow");
  if (abs < 3600) return rtf().format(Math.round(s / 60), "minute");
  if (abs < 86400) return rtf().format(Math.round(s / 3600), "hour");
  if (abs < 86400 * 30) return rtf().format(Math.round(s / 86400), "day");
  return dateFmt().format(new Date(iso));
}

export function plural(n: number, one: string, many: string): string {
  return `${count(n)} ${n > 1 ? many : one}`;
}

export function initials(title: string): string {
  const words = title.replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words[0]![0]! + words[1]![0]! : (words[0] ?? "?").slice(0, 2)).toUpperCase();
}
