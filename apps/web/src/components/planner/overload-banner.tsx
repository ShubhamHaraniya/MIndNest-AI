"use client";

import { AlertTriangle } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/kit/button";
import { useLocale, useT } from "@/i18n/client";
import { taskTitle } from "@/lib/planner";
import type { Overload, StudyTask } from "@/lib/types";

import { dayLabel, stateOf } from "./model";
import type { Planner } from "./use-planner";

const SHOWN = 3;

/** The task that best relieves a full day: the smallest open task that covers the excess, or the
 *  biggest one when none is big enough. */
export function taskToMove(tasks: StudyTask[], excess: number): StudyTask | null {
  const open = tasks.filter((task) => stateOf(task) === "pending");
  if (open.length === 0) return null;
  const enough = open.filter((task) => task.minutes >= excess).sort((a, b) => a.minutes - b.minutes);
  if (enough.length > 0) return enough[0];
  return [...open].sort((a, b) => b.minutes - a.minutes)[0];
}

/** Days that hold more than the student said they can do, each with a way to fix it. */
export function OverloadBanner({
  planner,
  onShowDay,
}: {
  planner: Planner;
  onShowDay: (day: string) => void;
}) {
  const t = useT();
  const locale = useLocale();
  const [moving, setMoving] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  const today = planner.today;
  const flagged = planner.overload.filter((entry) => today === null || entry.day >= today);
  if (flagged.length === 0) return null;
  const shown = all ? flagged : flagged.slice(0, SHOWN);

  async function move(entry: Overload) {
    if (!entry.suggested) return;
    const task = taskToMove(
      planner.tasks.filter((item) => item.planned_for === entry.day),
      entry.excess,
    );
    if (!task) return;
    setMoving(entry.day);
    try {
      await planner.update(task, { planned_for: entry.suggested });
    } finally {
      setMoving(null);
    }
  }

  return (
    <section
      aria-labelledby="overload-title"
      className="rounded-card border border-danger/40 bg-danger-soft px-3.5 py-3"
    >
      <h2 id="overload-title" className="flex items-center gap-2 text-[13px] font-semibold text-danger">
        <AlertTriangle className="h-4 w-4" aria-hidden />
        {t("pl.over.title", { count: flagged.length })}
      </h2>
      <ul className="mt-2 space-y-2">
        {shown.map((entry) => {
          const candidate = taskToMove(
            planner.tasks.filter((item) => item.planned_for === entry.day),
            entry.excess,
          );
          return (
            <li key={entry.day} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 text-[13px]">
              <p className="min-w-0 flex-1">
                <span className="font-medium">{dayLabel(entry.day, locale)}</span>
                {" · "}
                {entry.day_off
                  ? t("pl.over.dayOff", { minutes: entry.minutes })
                  : t("pl.over.line", { minutes: entry.minutes, limit: entry.limit, excess: entry.excess })}
              </p>
              <span className="flex flex-wrap gap-1.5">
                <Button size="sm" variant="secondary" onClick={() => onShowDay(entry.day)}>
                  {t("pl.over.show")}
                </Button>
                {entry.suggested && candidate ? (
                  <Button size="sm" loading={moving === entry.day} onClick={() => void move(entry)}>
                    {t("pl.over.move", {
                      task: truncate(taskTitle(candidate, t), 28),
                      day: dayLabel(entry.suggested, locale, "short"),
                    })}
                  </Button>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
      {flagged.length > SHOWN ? (
        <button type="button" onClick={() => setAll(!all)} className="mt-2 text-xs text-danger underline">
          {all ? t("pl.over.fewer") : t("pl.over.more", { count: flagged.length - SHOWN })}
        </button>
      ) : null}
    </section>
  );
}

function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}
