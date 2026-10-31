"use client";

import clsx from "clsx";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { useEffect, useMemo } from "react";

import { Button } from "@/components/kit/button";
import { IconButton } from "@/components/subjects/bits";
import { useLocale, useT } from "@/i18n/client";
import { addDays, parseDay } from "@/lib/planner";
import type { StudyTask } from "@/lib/types";

import { LoadMeter, MiniTask } from "./day-bits";
import { dayLabel, groupByDay, loadOf, overloadMap, weekDays } from "./model";
import type { Planner } from "./use-planner";

/** Seven days side by side (stacked on a phone), each with its load against the daily limit. */
export function WeekView({
  planner,
  anchor,
  onAnchor,
  onToggle,
  onOpen,
  onAdd,
  today,
}: {
  planner: Planner;
  anchor: string;
  onAnchor: (day: string) => void;
  onToggle: (task: StudyTask) => void;
  onOpen: (task: StudyTask) => void;
  onAdd: (day: string) => void;
  today: string;
}) {
  const t = useT();
  const locale = useLocale();
  const days = weekDays(anchor);
  const { show } = planner;
  const first = days[0];
  const last = days[6];
  useEffect(() => {
    show(first, last);
  }, [show, first, last]);
  const byDay = useMemo(() => groupByDay(planner.tasks), [planner.tasks]);
  const over = useMemo(() => overloadMap(planner.overload), [planner.overload]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-[13px] font-semibold">
          {dayLabel(days[0], locale, "short")} – {dayLabel(days[6], locale, "short")}
        </h2>
        <div className="flex items-center gap-1">
          <IconButton label={t("pl.nav.prevWeek")} onClick={() => onAnchor(addDays(days[0], -7))}>
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </IconButton>
          <Button size="sm" variant="secondary" onClick={() => onAnchor(today)}>
            {t("pl.nav.thisWeek")}
          </Button>
          <IconButton label={t("pl.nav.nextWeek")} onClick={() => onAnchor(addDays(days[0], 7))}>
            <ChevronRight className="h-4 w-4" aria-hidden />
          </IconButton>
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-4 xl:grid-cols-7">
        {days.map((day) => {
          const tasks = byDay.get(day) ?? [];
          const load = loadOf(tasks);
          const off = planner.daysOff.includes((parseDay(day).getDay() + 6) % 7);
          const flagged = over.get(day);
          return (
            <section
              key={day}
              aria-label={dayLabel(day, locale)}
              className={clsx(
                "flex min-h-32 flex-col gap-2 rounded-card border bg-surface p-2.5 shadow-card",
                day === today ? "border-primary ring-2 ring-primary/15" : flagged ? "border-danger/50" : "border-border",
              )}
            >
              <header className="flex items-center justify-between gap-2">
                <p className={clsx("text-xs font-semibold", day === today && "text-brand")}>
                  {dayLabel(day, locale, "weekday")} <span className="tabular font-normal text-muted">{parseDay(day).getDate()}</span>
                  {off ? <span className="ml-1 font-normal text-faint">· {t("pl.dayOff")}</span> : null}
                </p>
                <IconButton label={t("pl.addOn", { day: dayLabel(day, locale, "short") })} onClick={() => onAdd(day)} className="h-6 w-6">
                  <Plus className="h-3.5 w-3.5" aria-hidden />
                </IconButton>
              </header>
              <LoadMeter minutes={load} limit={planner.dailyMinutes} dayOff={off && load > 0} compact />
              {tasks.length > 0 ? (
                <ul className="space-y-1">
                  {tasks.map((task) => (
                    <MiniTask key={task.id} task={task} onToggle={onToggle} onOpen={onOpen} />
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-faint">{t("pl.week.free")}</p>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
