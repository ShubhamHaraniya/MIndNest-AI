"use client";

import clsx from "clsx";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/kit/button";
import { Panel } from "@/components/kit/panel";
import { IconButton } from "@/components/subjects/bits";
import { useLocale, useT } from "@/i18n/client";
import { monthGrid, parseDay, taskTitle, weekdayName } from "@/lib/planner";
import type { StudyTask } from "@/lib/types";

import { dayLabel, groupByDay, loadOf, monthStart, overloadMap, shiftMonth, stateOf } from "./model";
import { TaskList, type TaskActions } from "./task-row";
import type { Planner } from "./use-planner";

const SHOWN = 3;

/** A month grid: each day shows its first tasks and turns red when it holds too much. Pick a day
 *  to see its tasks underneath and add to it. */
export function MonthView({
  planner,
  anchor,
  onAnchor,
  actions,
  onAdd,
  today,
}: {
  planner: Planner;
  anchor: string;
  onAnchor: (day: string) => void;
  actions: TaskActions;
  onAdd: (day: string) => void;
  today: string;
}) {
  const t = useT();
  const locale = useLocale();
  const first = monthStart(anchor);
  const month = parseDay(first).getMonth();
  const grid = useMemo(() => monthGrid(parseDay(first).getFullYear(), month), [first, month]);
  const [selected, setSelected] = useState(today);
  const { show } = planner;
  const gridFirst = grid[0];
  const gridLast = grid[grid.length - 1];
  useEffect(() => {
    show(gridFirst, gridLast);
  }, [show, gridFirst, gridLast]);

  const byDay = useMemo(() => groupByDay(planner.tasks), [planner.tasks]);
  const over = useMemo(() => overloadMap(planner.overload), [planner.overload]);
  const chosen: StudyTask[] = byDay.get(selected) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-[13px] font-semibold">
          {parseDay(first).toLocaleDateString(locale, { month: "long", year: "numeric" })}
        </h2>
        <div className="flex items-center gap-1">
          <IconButton label={t("pl.nav.prevMonth")} onClick={() => onAnchor(shiftMonth(first, -1))}>
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </IconButton>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              onAnchor(today);
              setSelected(today);
            }}
          >
            {t("pl.nav.thisMonth")}
          </Button>
          <IconButton label={t("pl.nav.nextMonth")} onClick={() => onAnchor(shiftMonth(first, 1))}>
            <ChevronRight className="h-4 w-4" aria-hidden />
          </IconButton>
        </div>
      </div>

      <div className="overflow-x-auto">
        <div className="grid min-w-[40rem] grid-cols-7 gap-px overflow-hidden rounded-card border border-border bg-border">
          {[0, 1, 2, 3, 4, 5, 6].map((index) => (
            <div key={index} className="bg-surface-2 px-2 py-1 text-[11px] font-medium uppercase tracking-wide text-muted rtl:tracking-normal">
              {weekdayName(index, locale)}
            </div>
          ))}
          {grid.map((day) => {
            const tasks = byDay.get(day) ?? [];
            const inMonth = parseDay(day).getMonth() === month;
            const flagged = over.get(day);
            const live = tasks.filter((task) => stateOf(task) !== "cancelled");
            return (
              <button
                key={day}
                type="button"
                onClick={() => setSelected(day)}
                aria-pressed={selected === day}
                aria-label={`${dayLabel(day, locale)}${live.length ? ` · ${t("pl.month.tasks", { count: live.length })}` : ""}${flagged ? ` · ${t("pl.over.flag")}` : ""}`}
                className={clsx(
                  "flex min-h-24 flex-col items-stretch gap-1 bg-surface p-1.5 text-left hover:bg-surface-2",
                  !inMonth && "bg-surface-2/60 text-faint",
                  selected === day && "outline outline-2 -outline-offset-2 outline-primary",
                )}
              >
                <span className="flex items-center justify-between">
                  <span
                    className={clsx(
                      "tabular flex h-5 min-w-5 items-center justify-center rounded-full px-1 text-xs",
                      day === today && "bg-primary font-semibold text-on-primary",
                    )}
                  >
                    {parseDay(day).getDate()}
                  </span>
                  {flagged ? <span className="h-2 w-2 rounded-full bg-danger" aria-hidden /> : null}
                </span>
                {live.slice(0, SHOWN).map((task) => (
                  <span
                    key={task.id}
                    className={clsx(
                      "truncate rounded-md px-1.5 text-[11px] leading-4",
                      stateOf(task) === "completed"
                        ? "bg-success-soft text-success line-through"
                        : stateOf(task) === "overdue"
                          ? "bg-danger-soft text-danger"
                          : "bg-primary-soft text-brand",
                    )}
                  >
                    {taskTitle(task, t)}
                  </span>
                ))}
                {live.length > SHOWN ? <span className="px-1 text-[11px] text-muted">{t("pl.month.more", { count: live.length - SHOWN })}</span> : null}
              </button>
            );
          })}
        </div>
      </div>

      <Panel
        id="month-day"
        title={dayLabel(selected, locale)}
        description={chosen.length ? t("planner.progress", { done: chosen.filter((x) => stateOf(x) === "completed").length, total: chosen.filter((x) => stateOf(x) !== "cancelled").length, minutes: loadOf(chosen) }) : undefined}
        action={
          <Button size="sm" variant="secondary" onClick={() => onAdd(selected)}>
            {t("pl.addTask")}
          </Button>
        }
      >
        {chosen.length === 0 ? (
          <p className="px-3.5 py-6 text-center text-[13px] text-muted">{t("pl.month.dayEmpty")}</p>
        ) : (
          <TaskList tasks={chosen} actions={actions} today={today} label={dayLabel(selected, locale)} />
        )}
      </Panel>
    </div>
  );
}
