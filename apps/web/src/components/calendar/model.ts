import { taskTitle } from "@/lib/planner";
import type { TFunction } from "@/i18n/translate";
import type { CalendarEvent } from "@/lib/types";

export type CalendarMode = "month" | "week" | "day" | "agenda";
export const MODES: CalendarMode[] = ["month", "week", "day", "agenda"];
export const KINDS = ["exam", "assignment", "event", "task", "revision"] as const;
/** The calendar API answers at most this many days at once. */
export const MAX_DAYS = 62;
export const AGENDA_DAYS = 30;

export const KIND_STYLE: Record<CalendarEvent["kind"], string> = {
  exam: "bg-danger-soft text-danger",
  assignment: "bg-warning-soft text-warning",
  event: "bg-info-soft text-info",
  task: "bg-primary-soft text-brand",
  revision: "bg-success-soft text-success",
};

/** The solid colour of each kind, for the legend dots and the edge of a chip. */
export const KIND_DOT: Record<CalendarEvent["kind"], string> = {
  exam: "bg-danger",
  assignment: "bg-warning",
  event: "bg-info",
  task: "bg-primary",
  revision: "bg-success",
};

export const KIND_EDGE: Record<CalendarEvent["kind"], string> = {
  exam: "border-l-danger",
  assignment: "border-l-warning",
  event: "border-l-info",
  task: "border-l-primary",
  revision: "border-l-success",
};

export function eventLabel(event: CalendarEvent, t: TFunction): string {
  if (event.kind === "revision") return t("calendar.revision", { count: event.count ?? 0 });
  if (event.kind === "task") return taskTitle({ title: event.title, template: event.template, params: event.params }, t);
  return event.title;
}

export function eventHref(event: CalendarEvent): string | null {
  if (event.kind === "assignment" && event.id) return `/assignments/${event.id}`;
  if (event.kind === "exam" || event.kind === "task") return "/planner";
  if (event.kind === "revision") return "/quizzes";
  return null;
}

/** "14:30–16:00" for a timed event, null for everything else. */
export function timeRange(event: CalendarEvent): string | null {
  if (event.kind !== "event" || !event.start_time) return null;
  const [hours, minutes] = event.start_time.split(":").map(Number);
  const end = hours * 60 + minutes + (event.minutes ?? 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  const clock = `${pad(Math.floor(end / 60) % 24)}:${pad(end % 60)}`;
  return `${event.start_time}–${clock}${end >= 24 * 60 ? " +1" : ""}`;
}

export function isCancelled(event: CalendarEvent): boolean {
  return event.kind === "task" && event.state === "cancelled";
}

export function groupByDay(events: CalendarEvent[]): Map<string, CalendarEvent[]> {
  const groups = new Map<string, CalendarEvent[]>();
  for (const event of events) {
    const list = groups.get(event.day);
    if (list) list.push(event);
    else groups.set(event.day, [event]);
  }
  return groups;
}

/** A fresh name for one "add event" request, so sending it twice adds it once. */
export function newRequestKey(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `r${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
  }
}
