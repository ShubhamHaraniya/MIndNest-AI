import type { Tone } from "@/components/kit/badge";
import { addDays, formatDay, parseDay } from "@/lib/planner";
import type { Overload, StudyTask, TaskState } from "@/lib/types";

export type PlannerMode = "today" | "week" | "month" | "timeline" | "tasks";
export const MODES: PlannerMode[] = ["today", "week", "month", "timeline", "tasks"];

/** How many days back (for what is overdue) and ahead the planner loads at once. The API allows
 *  at most 120 days in one request. */
export const BACK_DAYS = 30;
export const SPAN_DAYS = 120;

export const STATE_TONE: Record<TaskState, Tone> = {
  pending: "neutral",
  completed: "success",
  overdue: "danger",
  cancelled: "neutral",
};

/** The state to show. Older servers did not send one, so fall back to the stored status. */
export function stateOf(task: StudyTask): TaskState {
  if (task.state) return task.state;
  return task.status === "done" ? "completed" : task.status === "todo" ? "pending" : "cancelled";
}

export function isOpen(task: StudyTask): boolean {
  const state = stateOf(task);
  return state === "pending" || state === "overdue";
}

/** Monday of the week that holds `value`. */
export function weekStart(value: string): string {
  const date = parseDay(value);
  return addDays(value, -((date.getDay() + 6) % 7));
}

export function weekDays(value: string): string[] {
  const first = weekStart(value);
  return Array.from({ length: 7 }, (_, i) => addDays(first, i));
}

export function monthStart(value: string): string {
  const date = parseDay(value);
  return formatDay(new Date(date.getFullYear(), date.getMonth(), 1));
}

export function shiftMonth(value: string, by: number): string {
  const date = parseDay(value);
  return formatDay(new Date(date.getFullYear(), date.getMonth() + by, 1));
}

export function groupByDay(tasks: StudyTask[]): Map<string, StudyTask[]> {
  const groups = new Map<string, StudyTask[]>();
  for (const task of tasks) {
    const list = groups.get(task.planned_for);
    if (list) list.push(task);
    else groups.set(task.planned_for, [task]);
  }
  return groups;
}

/** Minutes that count towards a day's load: to do or done, not cancelled. */
export function loadOf(tasks: StudyTask[]): number {
  return tasks.reduce((sum, task) => (stateOf(task) === "cancelled" ? sum : sum + task.minutes), 0);
}

export function overloadMap(overload: Overload[]): Map<string, Overload> {
  return new Map(overload.map((entry) => [entry.day, entry]));
}

export type TaskFilter = "open" | "overdue" | "completed" | "cancelled" | "all";
export const FILTERS: TaskFilter[] = ["open", "overdue", "completed", "cancelled", "all"];

export function matchesFilter(task: StudyTask, filter: TaskFilter): boolean {
  const state = stateOf(task);
  switch (filter) {
    case "open":
      return state === "pending" || state === "overdue";
    case "overdue":
      return state === "overdue";
    case "completed":
      return state === "completed";
    case "cancelled":
      return state === "cancelled";
    default:
      return true;
  }
}

export function countStates(tasks: StudyTask[]): Record<TaskState, number> {
  const counts: Record<TaskState, number> = { pending: 0, completed: 0, overdue: 0, cancelled: 0 };
  for (const task of tasks) counts[stateOf(task)] += 1;
  return counts;
}

export function dayLabel(value: string, locale: string, style: "long" | "short" | "weekday" = "long"): string {
  const date = parseDay(value);
  if (style === "weekday") return date.toLocaleDateString(locale, { weekday: "short" });
  if (style === "short") return date.toLocaleDateString(locale, { day: "numeric", month: "short" });
  return date.toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "long" });
}
