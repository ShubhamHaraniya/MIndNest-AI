import type { TFunction } from "@/i18n/translate";

import type { StudyTask } from "./types";

/** A "YYYY-MM-DD" string as a local Date (never shifted by the time zone). */
export function parseDay(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

export function formatDay(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function addDays(value: string, days: number): string {
  const date = parseDay(value);
  date.setDate(date.getDate() + days);
  return formatDay(date);
}

/** The six weeks (Monday first) that show a month, as day strings. */
export function monthGrid(year: number, month: number): string[] {
  const first = new Date(year, month, 1);
  const offset = (first.getDay() + 6) % 7; // Monday = 0
  const start = new Date(year, month, 1 - offset);
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    return formatDay(d);
  });
}

/** What to show for a task: the planner's own tasks are translated, the student's are as typed. */
export function taskTitle(
  task: { title: string; template: string | null; params: Record<string, string | number> | null },
  t: TFunction,
): string {
  if (!task.template) return task.title;
  // The key is built from the template name the server stored; an unknown one falls back to
  // the English title instead of showing a raw key.
  const key = `planner.t.${task.template}` as Parameters<TFunction>[0];
  const text = t(key, (task.params ?? {}) as Record<string, string | number>);
  return text === key ? task.title : text;
}

/** Where a planned task leads. */
export function taskHref(task: Pick<StudyTask, "kind" | "assignment_id">): string | null {
  if (task.kind === "assignment" && task.assignment_id) return `/assignments/${task.assignment_id}`;
  if (task.kind === "revise" || task.kind === "quiz") return "/quizzes";
  return null;
}

export function totalMinutes(tasks: StudyTask[]): number {
  return tasks.reduce((sum, task) => sum + task.minutes, 0);
}

export const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6] as const; // Monday first, as the API counts them

export function weekdayName(index: number, locale: string): string {
  // 2024-01-01 was a Monday.
  return new Date(2024, 0, 1 + index).toLocaleDateString(locale, { weekday: "short" });
}
