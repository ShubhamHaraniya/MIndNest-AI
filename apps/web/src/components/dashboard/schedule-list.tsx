"use client";

import clsx from "clsx";
import { Check, Loader2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/kit/badge";
import { Panel } from "@/components/kit/panel";
import { useToast } from "@/components/kit/toast";
import { useT } from "@/i18n/client";
import type { MessageKey } from "@/i18n/translate";
import { api } from "@/lib/api";
import type { ScheduleTask } from "@/lib/types";

const KIND_KEYS: Record<string, MessageKey> = {
  revise: "wb.kind.revise",
  assignment: "wb.kind.assignment",
  quiz: "wb.kind.quiz",
  custom: "wb.kind.custom",
};

/** Today's tasks as a checklist. Ticking one marks it done in the planner straight away (and
 *  puts it back if the server refuses), so the dashboard is where the day is actually worked. */
export function ScheduleList({
  tasks: initial,
  dailyMinutes,
  revisionDue,
}: {
  tasks: ScheduleTask[];
  dailyMinutes: number;
  revisionDue: number;
}) {
  const t = useT();
  const toast = useToast();
  const [tasks, setTasks] = useState(initial);
  const [pending, setPending] = useState<Set<string>>(new Set());

  async function toggle(task: ScheduleTask) {
    const next = task.status === "done" ? "todo" : "done";
    setTasks((current) => current.map((item) => (item.id === task.id ? { ...item, status: next } : item)));
    setPending((current) => new Set(current).add(task.id));
    try {
      await api(`/planner/tasks/${task.id}`, { method: "PATCH", body: { status: next } });
    } catch {
      setTasks((current) => current.map((item) => (item.id === task.id ? { ...item, status: task.status } : item)));
      toast.error(t("wb.today.failed"));
    } finally {
      setPending((current) => {
        const copy = new Set(current);
        copy.delete(task.id);
        return copy;
      });
    }
  }

  const done = tasks.filter((task) => task.status === "done");
  const minutesAll = tasks.reduce((sum, task) => sum + task.minutes, 0);
  const minutesDone = done.reduce((sum, task) => sum + task.minutes, 0);

  return (
    <Panel
      id="today"
      title={t("wb.today.title")}
      action={
        <Link href="/planner" className="font-medium text-brand underline-offset-2 hover:underline">
          {t("wb.today.openPlanner")}
        </Link>
      }
      footer={
        tasks.length > 0 || revisionDue > 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <span className="tabular">
              {tasks.length > 0
                ? t("wb.today.summary", { done: done.length, total: tasks.length, minutes: minutesDone, planned: minutesAll })
                : t("wb.today.target", { minutes: dailyMinutes })}
              {tasks.length > 0 ? ` · ${t("wb.today.target", { minutes: dailyMinutes })}` : ""}
            </span>
            {revisionDue > 0 ? (
              <Link href="/quizzes" className="font-medium text-brand underline-offset-2 hover:underline">
                {t("wb.today.revision", { count: revisionDue })}
              </Link>
            ) : null}
          </div>
        ) : undefined
      }
    >
      {tasks.length === 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3 px-3.5 py-5">
          <p className="text-sm text-muted">{t("wb.today.empty")}</p>
          <Link
            href="/planner"
            className="inline-flex h-7 items-center rounded border border-border-strong px-2.5 text-xs font-medium hover:bg-surface-2"
          >
            {t("wb.today.plan")}
          </Link>
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {tasks.map((task) => {
            const isDone = task.status === "done";
            const busy = pending.has(task.id);
            return (
              <li key={task.id} className="flex items-center gap-3 px-3.5 py-2">
                <button
                  type="button"
                  role="checkbox"
                  aria-checked={isDone}
                  aria-label={t(isDone ? "wb.today.markTodo" : "wb.today.markDone", { title: task.title })}
                  onClick={() => void toggle(task)}
                  disabled={busy}
                  className={clsx(
                    "flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-sm border transition-colors",
                    isDone ? "border-primary bg-primary text-on-primary" : "border-border-strong bg-surface hover:border-primary",
                  )}
                >
                  {busy ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : isDone ? <Check className="h-3 w-3" aria-hidden /> : null}
                </button>
                <div className="min-w-0 flex-1">
                  <p className={clsx("truncate text-[13px]", isDone && "text-faint line-through", task.state === "cancelled" && "text-faint")}>
                    {task.href ? (
                      <Link href={task.href} className="hover:text-brand hover:underline" title={task.title}>
                        {task.title}
                      </Link>
                    ) : (
                      task.title
                    )}
                  </p>
                  <p className="truncate text-xs text-muted">
                    {t(KIND_KEYS[task.kind] ?? "wb.kind.custom")}
                    {task.subject_name ? ` · ${task.subject_name}` : ""}
                  </p>
                </div>
                {task.state === "overdue" ? <Badge tone="danger">{t("dbx.state.overdue")}</Badge> : null}
                {task.state === "cancelled" ? <Badge tone="neutral">{t("dbx.state.cancelled")}</Badge> : null}
                <span className="tabular shrink-0 text-xs text-muted">
                  {task.minutes} {t("dashboard.minShort")}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
