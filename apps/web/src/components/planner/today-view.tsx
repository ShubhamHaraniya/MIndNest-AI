"use client";

import { CalendarPlus, PartyPopper } from "lucide-react";

import { Button } from "@/components/kit/button";
import { Panel } from "@/components/kit/panel";
import { ProgressBar } from "@/components/kit/progress";
import { EmptyState } from "@/components/kit/states";
import { useLocale, useT } from "@/i18n/client";

import { LoadMeter } from "./day-bits";
import { dayLabel, isOpen, loadOf, stateOf } from "./model";
import { TaskList, type TaskActions } from "./task-row";
import type { Planner } from "./use-planner";

/** What to do today: what is overdue, today's list with progress, and what comes next. */
export function TodayView({
  planner,
  actions,
  onAdd,
  today,
}: {
  planner: Planner;
  actions: TaskActions;
  onAdd: (day: string) => void;
  today: string;
}) {
  const t = useT();
  const locale = useLocale();
  const overdue = planner.tasks.filter((task) => stateOf(task) === "overdue");
  const todays = planner.tasks.filter((task) => task.planned_for === today);
  const active = todays.filter((task) => stateOf(task) !== "cancelled");
  const finished = active.filter((task) => stateOf(task) === "completed").length;
  const cancelled = todays.length - active.length;
  const next = planner.tasks.filter((task) => task.planned_for > today && isOpen(task)).slice(0, 6);
  const allDone = active.length > 0 && finished === active.length;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="space-y-4">
        {overdue.length > 0 ? (
          <Panel
            id="overdue"
            title={t("pl.overdue.title", { count: overdue.length })}
            description={t("pl.overdue.hint")}
            className="border-danger/40"
          >
            <TaskList tasks={overdue} actions={actions} today={today} showDay label={t("pl.overdue.label")} />
          </Panel>
        ) : null}

        <Panel
          id="today"
          title={
            <>
              {t("planner.today")}
              <span className="ml-2 font-normal text-muted">{dayLabel(today, locale)}</span>
            </>
          }
          action={
            <Button size="sm" variant="secondary" onClick={() => onAdd(today)}>
              <CalendarPlus className="h-3.5 w-3.5" aria-hidden />
              {t("pl.addTask")}
            </Button>
          }
        >
          {active.length > 0 ? (
            <div className="space-y-1.5 border-b border-border px-3.5 py-3">
              <div className="flex items-baseline justify-between gap-3 text-xs text-muted">
                <span>{t("planner.progress", { done: finished, total: active.length, minutes: loadOf(active) })}</span>
                {cancelled > 0 ? <span>{t("pl.cancelledCount", { count: cancelled })}</span> : null}
              </div>
              <ProgressBar value={finished / active.length} tone={allDone ? "success" : "brand"} label={t("planner.today")} />
              <LoadMeter minutes={loadOf(active)} limit={planner.dailyMinutes} dayOff={false} compact />
            </div>
          ) : null}
          {todays.length === 0 ? (
            <EmptyState compact icon={PartyPopper} title={t("pl.today.emptyTitle")} description={t("planner.todayEmpty")}>
              <Button size="sm" onClick={() => onAdd(today)}>
                {t("pl.addTask")}
              </Button>
            </EmptyState>
          ) : (
            <TaskList tasks={todays} actions={actions} today={today} label={t("planner.today")} />
          )}
        </Panel>
      </div>

      <Panel id="next" title={t("planner.upcoming")}>
        {next.length === 0 ? (
          <p className="px-3.5 py-6 text-center text-[13px] text-muted">{t("pl.next.empty")}</p>
        ) : (
          <TaskList tasks={next} actions={actions} today={today} showDay label={t("planner.upcoming")} />
        )}
      </Panel>
    </div>
  );
}
