/** Small, locale-aware formatters shared by the pages. All take the UI language ("en" | "hi" |
 *  "gu") so dates and relative times read in the student's own language. */

const BCP47: Record<string, string> = { en: "en-IN", hi: "hi-IN", gu: "gu-IN" };

export function bcp47(locale: string): string {
  return BCP47[locale] ?? "en-IN";
}

/** "2026-10-29" -> a local Date (no time-zone shift). */
export function parseDay(value: string): Date {
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function formatDay(value: string, locale: string, options: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(bcp47(locale), options).format(parseDay(value));
}

/** "3 hours ago", "yesterday", "2 days ago"; falls back to a short date after a month. */
export function relativeTime(iso: string, locale: string, now: number = Date.now()): string {
  const then = new Date(iso).getTime();
  const seconds = Math.round((then - now) / 1000);
  const abs = Math.abs(seconds);
  const rtf = new Intl.RelativeTimeFormat(bcp47(locale), { numeric: "auto" });
  if (abs < 60) return rtf.format(0, "second");
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), "hour");
  if (abs < 86400 * 30) return rtf.format(Math.round(seconds / 86400), "day");
  return new Intl.DateTimeFormat(bcp47(locale), { day: "numeric", month: "short", year: "numeric" }).format(
    new Date(then),
  );
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`;
}

/** 95 -> "1 h 35 min" (using the translated unit words). */
export function formatMinutes(minutes: number, hour: string, min: string): string {
  if (minutes < 60) return `${minutes} ${min}`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h} ${hour}` : `${h} ${hour} ${m} ${min}`;
}

export function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** "29 Oct 2026, 6:30 pm" in the student's language. */
export function formatDateTime(iso: string | number, locale: string): string {
  return new Intl.DateTimeFormat(bcp47(locale), { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" }).format(
    new Date(iso),
  );
}

/** "6:30:12 pm" in the student's language. */
export function formatTime(iso: string | number, locale: string): string {
  return new Intl.DateTimeFormat(bcp47(locale), { hour: "numeric", minute: "2-digit", second: "2-digit" }).format(new Date(iso));
}
