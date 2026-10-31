"use client";

import clsx from "clsx";
import { Ban, Check, Pencil, Pin, RotateCcw, Trash2 } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/kit/badge";
import { IconButton } from "@/components/subjects/bits";
import { useLocale, useT } from "@/i18n/client";
import { parseDay, taskHref, taskTitle } from "@/lib/planner";
import type { StudyTask } from "@/lib/types";

import { stateOf } from "./model";

export type TaskActions = {
  onToggle: (task: StudyTask) => void;
  onCancel: (task: StudyTask) => void;
  onRestore: (task: StudyTask) => void;
  onEdit: (task: StudyTask) => void;
  onDelete: (task: StudyTask) => void;
};

/** One task: tick it off, open what it is about, and change or drop it. */
export function TaskRow({
  task,
  actions,
  showDay,
  today,
}: {
  task: StudyTask;
  actions: TaskActions;
  /** Name the day in the second line (for lists that are not grouped by day). */
  showDay?: boolean;
  today: string;
}) {
  const t = useT();
  const locale = useLocale();
  const state = stateOf(task);
  const done = state === "completed";
  const cancelled = state === "cancelled";
  const href = taskHref(task);
  const title = taskTitle(task, t);
  const late = state === "overdue" ? Math.round((parseDay(today).getTime() - parseDay(task.planned_for).getTime()) / 86_400_000) : 0;

  return (
    <li className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-surface-2/60">
      <button
        type="button"
        role="checkbox"
        aria-checked={done}
        aria-label={done ? t("planner.markTodo") : t("planner.markDone")}
        disabled={cancelled}
        onClick={() => actions.onToggle(task)}
        className={clsx(
          "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition-colors disabled:opacity-40",
          done ? "border-success bg-success text-on-primary" : "border-border-strong bg-surface hover:border-primary hover:bg-primary-soft",
        )}
      >
        {done ? <Check className="h-3.5 w-3.5" aria-hidden /> : null}
      </button>

      <div className="min-w-0 flex-1">
        <p className={clsx("text-[13px] leading-5", (done || cancelled) && "text-muted line-through")}>
          {href && !cancelled ? (
            <Link href={href} className="hover:text-brand hover:underline">
              {title}
            </Link>
          ) : (
            title
          )}
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
          {showDay ? (
            <span>{parseDay(task.planned_for).toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" })}</span>
          ) : null}
          <span className="tabular">{t("planner.minutes", { n: task.minutes })}</span>
          {task.subject_name ? <span className="truncate">{task.subject_name}</span> : null}
          {state === "overdue" ? <Badge tone="danger">{t("pl.late", { count: late })}</Badge> : null}
          {cancelled ? <Badge>{t("pl.state.cancelled")}</Badge> : null}
          {task.source === "manual" ? <Badge tone="info">{t("pl.yours")}</Badge> : null}
          {task.pinned ? (
            <span className="inline-flex items-center gap-1 text-info" title={t("pl.pinned.hint")}>
              <Pin className="h-3 w-3" aria-hidden />
              {t("pl.pinned")}
            </span>
          ) : null}
        </p>
      </div>

      <span className="inline-flex shrink-0 items-center gap-0.5">
        <IconButton label={t("pl.edit")} onClick={() => actions.onEdit(task)}>
          <Pencil className="h-3.5 w-3.5" aria-hidden />
        </IconButton>
        {cancelled ? (
          <IconButton label={t("pl.restore")} onClick={() => actions.onRestore(task)}>
            <RotateCcw className="h-3.5 w-3.5" aria-hidden />
          </IconButton>
        ) : !done ? (
          <IconButton label={t("pl.cancel")} onClick={() => actions.onCancel(task)}>
            <Ban className="h-3.5 w-3.5" aria-hidden />
          </IconButton>
        ) : null}
        <IconButton label={t("common.delete")} danger onClick={() => actions.onDelete(task)}>
          <Trash2 className="h-3.5 w-3.5" aria-hidden />
        </IconButton>
      </span>
    </li>
  );
}

export function TaskList({
  tasks,
  actions,
  today,
  showDay,
  label,
}: {
  tasks: StudyTask[];
  actions: TaskActions;
  today: string;
  showDay?: boolean;
  label: string;
}) {
  return (
    <ul aria-label={label} className="divide-y divide-border">
      {tasks.map((task) => (
        <TaskRow key={task.id} task={task} actions={actions} today={today} showDay={showDay} />
      ))}
    </ul>
  );
}
