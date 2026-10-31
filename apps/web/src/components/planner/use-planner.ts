"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useToast } from "@/components/kit/toast";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { addDays } from "@/lib/planner";
import type { Exam, GenerateResult, Overload, StudyPreferences, StudyTask, TasksResponse } from "@/lib/types";

import { BACK_DAYS, SPAN_DAYS } from "./model";

export type TaskPatch = Partial<{
  title: string;
  planned_for: string;
  minutes: number;
  status: StudyTask["status"];
  subject_id: string | null;
}>;

export type NewTask = { title: string; planned_for: string; minutes: number; subject_id: string | null };

type Core = {
  today: string;
  dailyMinutes: number;
  daysOff: number[];
  tasks: StudyTask[];
  overload: Overload[];
  first: string;
  last: string;
};

/** Everything the planner shows: the tasks around today, the exams and the study preferences,
 *  plus the actions on them. Other months are fetched only when the student looks at them. */
export function usePlanner() {
  const t = useT();
  const toast = useToast();
  const [core, setCore] = useState<Core | null>(null);
  const [extra, setExtra] = useState<{ first: string; last: string; tasks: StudyTask[]; overload: Overload[] } | null>(null);
  const [exams, setExams] = useState<Exam[]>([]);
  const [prefs, setPrefs] = useState<StudyPreferences | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const focus = useRef<{ first: string; last: string } | null>(null);

  const fetchExtra = useCallback(async (base: Core | null) => {
    const want = focus.current;
    if (!want || !base || (want.first >= base.first && want.last <= base.last)) {
      setExtra(null);
      return;
    }
    // Only the part outside what is already loaded.
    const first = want.first < base.first ? want.first : addDays(base.last, 1);
    const last = want.last > base.last ? want.last : addDays(base.first, -1);
    try {
      const response = await api<TasksResponse>(`/planner/tasks?from=${first}&to=${last}`);
      setExtra({ first, last, tasks: response.items, overload: response.overload });
    } catch {
      setExtra(null);
    }
  }, []);

  const load = useCallback(async () => {
    try {
      // The server says what "today" is in the student's time zone; the window starts there.
      const probe = await api<TasksResponse>("/planner/tasks");
      const first = addDays(probe.today, -BACK_DAYS);
      const last = addDays(probe.today, SPAN_DAYS - BACK_DAYS - 1);
      const [wide, examList, preferences] = await Promise.all([
        api<TasksResponse>(`/planner/tasks?from=${first}&to=${last}`),
        api<Exam[]>("/exams"),
        api<StudyPreferences>("/planner/preferences"),
      ]);
      const next: Core = {
        today: wide.today,
        dailyMinutes: wide.daily_minutes,
        daysOff: wide.days_off,
        tasks: wide.items,
        overload: wide.overload,
        first,
        last,
      };
      setCore(next);
      setExams(examList);
      setPrefs(preferences);
      setError(null);
      await fetchExtra(next);
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setLoading(false);
    }
  }, [t, fetchExtra]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Tell the hook which days the current view shows, so it can load them if they are far away. */
  const show = useCallback(
    (first: string, last: string) => {
      const current = focus.current;
      if (current && current.first === first && current.last === last) return;
      focus.current = { first, last };
      void fetchExtra(core);
    },
    [core, fetchExtra],
  );

  const tasks = useMemo(() => {
    const merged = new Map<string, StudyTask>();
    for (const task of core?.tasks ?? []) merged.set(task.id, task);
    for (const task of extra?.tasks ?? []) merged.set(task.id, task);
    return [...merged.values()].sort(
      (a, b) => a.planned_for.localeCompare(b.planned_for) || Number(a.status !== "todo") - Number(b.status !== "todo"),
    );
  }, [core, extra]);

  const overload = useMemo(() => [...(core?.overload ?? []), ...(extra?.overload ?? [])], [core, extra]);

  async function run<T>(action: () => Promise<T>): Promise<T | null> {
    try {
      const result = await action();
      return result;
    } catch (caught) {
      toast.error(errorMessage(caught, t));
      return null;
    }
  }

  async function update(task: StudyTask, patch: TaskPatch): Promise<boolean> {
    const done = await run(() => api<StudyTask>(`/planner/tasks/${task.id}`, { method: "PATCH", body: patch }));
    if (done) await load();
    return done !== null;
  }

  async function add(draft: NewTask): Promise<boolean> {
    const done = await run(() => api<StudyTask>("/planner/tasks", { method: "POST", body: draft }));
    if (done) await load();
    return done !== null;
  }

  async function remove(task: StudyTask): Promise<boolean> {
    const done = await run(() => api(`/planner/tasks/${task.id}`, { method: "DELETE" }));
    // `api` resolves to undefined for 204, which is a success.
    const ok = done !== null;
    if (ok) await load();
    return ok;
  }

  async function generate(days: number): Promise<GenerateResult | null> {
    const result = await run(() => api<GenerateResult>("/planner/generate", { method: "POST", body: { days } }));
    if (result) await load();
    return result;
  }

  async function savePreferences(next: StudyPreferences): Promise<boolean> {
    const saved = await run(() => api<StudyPreferences>("/planner/preferences", { method: "PUT", body: next }));
    if (saved) await load();
    return saved !== null;
  }

  return {
    loading,
    error,
    today: core?.today ?? null,
    dailyMinutes: core?.dailyMinutes ?? prefs?.daily_minutes ?? 90,
    daysOff: core?.daysOff ?? prefs?.days_off ?? [],
    tasks,
    overload,
    exams,
    prefs,
    reload: load,
    show,
    update,
    add,
    remove,
    generate,
    savePreferences,
  };
}

export type Planner = ReturnType<typeof usePlanner>;
