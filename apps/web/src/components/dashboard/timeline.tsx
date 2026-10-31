"use client";

import clsx from "clsx";
import { Check, Loader2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/kit/badge";
import { Panel, PanelLink } from "@/components/kit/panel";
import { useToast } from "@/components/kit/toast";
import { Stagger, StaggerItem } from "@/components/motion/reveal";
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

/** Today as a vertical timeline: a lit line down the side, a node per task, the next open one pulsing.
 *  Ticking a node marks the task done in the planner straight away (and puts it back if the server refuses). */
export function StudyTimeline({
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
  const current = tasks.find((task) => task.status === "todo" && task.state !== "cancelled");

  return (
    <Panel
      id="today"
      title={t("wb.today.title")}
      className="h-full"
      action={<PanelLink href="/planner">{t("wb.today.openPlanner")}</PanelLink>}
      footer={
        tasks.length > 0 || revisionDue > 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <span className="tabular">
              {tasks.length > 0
                ? t("wb.today.summary", { done: done.length, total: tasks.length, minutes: minutesDone, planned: minutesAll })
                : t("wb.today.target", { minutes: dailyMinutes })}
            </span>
            {revisionDue > 0 ? <PanelLink href="/quizzes">{t("wb.today.revision", { count: revisionDue })}</PanelLink> : null}
          </div>
        ) : undefined
      }
    >
      {tasks.length === 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-6">
          <p className="text-sm text-muted">{t("wb.today.empty")}</p>
          <Link
            href="/planner"
            className="inline-flex h-8 items-center rounded-lg border border-border-strong bg-surface-2/60 px-3 text-xs font-medium hover:bg-surface-3/80"
          >
            {t("wb.today.plan")}
          </Link>
        </div>
      ) : (
        <Stagger as="ol" className="relative px-4 py-4">
          <span aria-hidden className="absolute bottom-6 top-6 w-px bg-gradient-to-b from-primary/60 via-border to-transparent [inset-inline-start:1.7rem]" />
          {tasks.map((task) => {
            const isDone = task.status === "done";
            const busy = pending.has(task.id);
            const isNow = current?.id === task.id;
            return (
              <StaggerItem as="li" key={task.id} className="relative flex items-start gap-3.5 py-2.5">
                <button
                  type="button"
                  role="checkbox"
                  aria-checked={isDone}
                  aria-label={t(isDone ? "wb.today.markTodo" : "wb.today.markDone", { title: task.title })}
                  onClick={() => void toggle(task)}
                  disabled={busy}
                  className={clsx(
                    "relative z-10 mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full border transition-all",
                    isDone
                      ? "border-primary bg-primary text-on-primary"
                      : isNow
                        ? "border-primary bg-surface-2 shadow-glow hover:bg-primary-soft"
                        : "border-border-strong bg-surface-2 hover:border-primary",
                  )}
                >
                  {isNow && !isDone ? <span aria-hidden className="absolute inset-0 animate-ping rounded-full bg-primary/30" /> : null}
                  {busy ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : isDone ? <Check className="h-3.5 w-3.5" strokeWidth={3} aria-hidden /> : null}
                </button>
                <div className="min-w-0 flex-1">
                  <p className={clsx("truncate text-[14px]", isDone || task.state === "cancelled" ? "text-faint line-through" : "font-medium")}>
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
                <span className="tabular shrink-0 pt-0.5 text-xs text-muted">
                  {task.minutes} {t("dashboard.minShort")}
                </span>
              </StaggerItem>
            );
          })}
        </Stagger>
      )}
    </Panel>
  );
}
