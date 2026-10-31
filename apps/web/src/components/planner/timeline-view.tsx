"use client";

import clsx from "clsx";
import { GraduationCap, ListChecks } from "lucide-react";
import { useEffect, useMemo } from "react";

import { Badge } from "@/components/kit/badge";
import { EmptyState } from "@/components/kit/states";
import { useLocale, useT } from "@/i18n/client";
import { addDays } from "@/lib/planner";

import { LoadMeter } from "./day-bits";
import { dayLabel, groupByDay, loadOf, overloadMap } from "./model";
import { TaskList, type TaskActions } from "./task-row";
import type { Planner } from "./use-planner";

const AHEAD_DAYS = 60;

/** What is coming, day by day: exams as markers, then the tasks of each day with its load. Days
 *  with nothing on them are left out. */
export function TimelineView({
  planner,
  actions,
  today,
}: {
  planner: Planner;
  actions: TaskActions;
  today: string;
}) {
  const t = useT();
  const locale = useLocale();
  const last = addDays(today, AHEAD_DAYS);
  const { show } = planner;
  useEffect(() => {
    show(today, last);
  }, [show, today, last]);

  const byDay = useMemo(() => groupByDay(planner.tasks.filter((task) => task.planned_for >= today && task.planned_for <= last)), [planner.tasks, today, last]);
  const over = useMemo(() => overloadMap(planner.overload), [planner.overload]);
  const exams = useMemo(() => planner.exams.filter((exam) => exam.exam_on >= today && exam.exam_on <= last), [planner.exams, today, last]);
  const days = useMemo(() => {
    const set = new Set<string>([...byDay.keys(), ...exams.map((exam) => exam.exam_on)]);
    return [...set].sort();
  }, [byDay, exams]);

  if (days.length === 0) {
    return <EmptyState icon={ListChecks} title={t("pl.timeline.emptyTitle")} description={t("pl.timeline.emptyBody")} />;
  }

  return (
    <ol className="relative ml-2 space-y-4 border-l border-border pl-5" aria-label={t("pl.mode.timeline")}>
      {days.map((day) => {
        const tasks = byDay.get(day) ?? [];
        const dayExams = exams.filter((exam) => exam.exam_on === day);
        const flagged = over.get(day);
        return (
          <li key={day} className="relative">
            <span
              aria-hidden
              className={clsx(
                "absolute -left-[1.72rem] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-bg",
                dayExams.length ? "bg-warning" : flagged ? "bg-danger" : day === today ? "bg-primary" : "bg-border-strong",
              )}
            />
            <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <h3 className="text-[13px] font-semibold">
                {dayLabel(day, locale)}
                {day === today ? <Badge tone="brand" className="ml-2">{t("planner.today")}</Badge> : null}
              </h3>
              <div className="w-40">
                <LoadMeter minutes={loadOf(tasks)} limit={planner.dailyMinutes} dayOff={flagged?.day_off} compact />
              </div>
            </div>
            {dayExams.map((exam) => (
              <p
                key={exam.id}
                className="mb-1.5 flex items-center gap-2 rounded-lg border border-warning/40 bg-warning-soft px-3 py-2 text-[13px]"
              >
                <GraduationCap className="h-4 w-4 shrink-0 text-warning" aria-hidden />
                <span className="font-medium">{exam.title}</span>
                {exam.subject_name ? <span className="text-muted">· {exam.subject_name}</span> : null}
              </p>
            ))}
            {tasks.length > 0 ? (
              <div className="rounded-card border border-border bg-surface shadow-card">
                <TaskList tasks={tasks} actions={actions} today={today} label={dayLabel(day, locale)} />
              </div>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
