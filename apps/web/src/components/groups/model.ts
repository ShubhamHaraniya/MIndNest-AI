import type { TFunction } from "@/i18n/translate";
import { bcp47 } from "@/lib/format";
import type { GroupRole, GroupSession } from "@/lib/types";

/** Owners and admins can pin, lock and remove other people's work. */
export const isAdminRole = (role: GroupRole): boolean => role === "owner" || role === "admin";

export const GROUP_TABS = ["files", "notes", "talk", "sessions", "members"] as const;
export type GroupTab = (typeof GROUP_TABS)[number];

/** Who wrote something. A person who left the group is "Former member": their work stays. */
export function personName(name: string | null, t: TFunction): string {
  return name ?? t("gc.former");
}

export function formatWhen(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(bcp47(locale), {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function formatDate(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(bcp47(locale), { day: "numeric", month: "short", year: "numeric" }).format(new Date(iso));
}

const pad = (n: number) => String(n).padStart(2, "0");

/** A moment as the value of a datetime-local field (in the browser's own time zone). */
export function toLocalInput(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** The moment a datetime-local field names, as the UTC time the server expects. */
export function fromLocalInput(value: string): string {
  return new Date(value).toISOString();
}

/** The next whole hour, for the "new session" form. */
export function nextHourInput(): string {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  return toLocalInput(d.toISOString());
}

export const SESSION_MINUTES = [30, 45, 60, 90, 120, 180] as const;
export const MIN_SESSION_MINUTES = 15;
export const MAX_SESSION_MINUTES = 720;

export const isOpen = (session: GroupSession): boolean => session.state === "upcoming" || session.state === "ongoing";
