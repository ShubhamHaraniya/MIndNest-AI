"use client";

import clsx from "clsx";
import { AlertTriangle, Check } from "lucide-react";

import { ProgressBar } from "@/components/kit/progress";
import { useT } from "@/i18n/client";
import { taskTitle } from "@/lib/planner";
import type { StudyTask } from "@/lib/types";

import { stateOf } from "./model";

/** How full a day is against the student's daily limit. Over the limit it turns red and says so. */
export function LoadMeter({
  minutes,
  limit,
  dayOff,
  compact,
}: {
  minutes: number;
  limit: number;
  dayOff?: boolean;
  compact?: boolean;
}) {
  const t = useT();
  if (minutes <= 0) return null;
  const over = dayOff || minutes > limit;
  const near = !over && minutes >= limit * 0.85;
  return (
    <div className={clsx("min-w-0", compact ? "space-y-0.5" : "space-y-1")}>
      <ProgressBar
        value={dayOff ? 1 : minutes / limit}
        tone={over ? "danger" : near ? "warning" : "brand"}
        label={t("pl.load.label", { minutes, limit })}
      />
      <p className={clsx("tabular flex items-center gap-1 text-[11px]", over ? "text-danger" : "text-muted")}>
        {over ? <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden /> : null}
        <span className="truncate">
          {dayOff ? t("pl.load.dayOff", { minutes }) : t("pl.load.of", { minutes, limit })}
        </span>
      </p>
    </div>
  );
}

/** A task as a small line inside a day cell: tick box, title (opens the editor), minutes. */
export function MiniTask({
  task,
  onToggle,
  onOpen,
}: {
  task: StudyTask;
  onToggle: (task: StudyTask) => void;
  onOpen: (task: StudyTask) => void;
}) {
  const t = useT();
  const state = stateOf(task);
  const done = state === "completed";
  const cancelled = state === "cancelled";
  return (
    <li
      className={clsx(
        "flex items-start gap-1.5 rounded-lg border px-1.5 py-1 text-xs",
        state === "overdue" ? "border-danger/40 bg-danger-soft" : "border-border bg-surface-2",
      )}
    >
      <button
        type="button"
        role="checkbox"
        aria-checked={done}
        aria-label={done ? t("planner.markTodo") : t("planner.markDone")}
        disabled={cancelled}
        onClick={() => onToggle(task)}
        className={clsx(
          "mt-px flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border disabled:opacity-40",
          done ? "border-success bg-success text-on-primary" : "border-border-strong bg-surface",
        )}
      >
        {done ? <Check className="h-2.5 w-2.5" aria-hidden /> : null}
      </button>
      <button
        type="button"
        onClick={() => onOpen(task)}
        className={clsx("min-w-0 flex-1 text-left leading-4 hover:text-brand", (done || cancelled) && "text-muted line-through")}
      >
        <span className="line-clamp-2">{taskTitle(task, t)}</span>
        <span className="tabular text-faint">{t("planner.minutes", { n: task.minutes })}</span>
      </button>
    </li>
  );
}
