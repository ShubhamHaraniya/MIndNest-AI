"use client";

import { AlertTriangle, ArrowRight, Check, CheckCircle2, Clock, GraduationCap, ListChecks, PartyPopper, Plus, Target } from "lucide-react";
import Link from "next/link";

import { Tile } from "@/components/dashboard/home-hero";
import { Button, ButtonLink } from "@/components/kit/button";
import { ProgressRing } from "@/components/kit/progress";
import { useT } from "@/i18n/client";
import { parseDay, taskHref, taskTitle } from "@/lib/planner";

import { loadOf, stateOf } from "./model";
import type { TaskActions } from "./task-row";
import type { Planner } from "./use-planner";

/** The top of the planner: the one task to do now, and four figures about today. */
export function PlanHero({
  planner,
  actions,
  today,
  onAdd,
}: {
  planner: Planner;
  actions: TaskActions;
  today: string;
  onAdd: (day: string) => void;
}) {
  const t = useT();
  const overdue = planner.tasks.filter((task) => stateOf(task) === "overdue");
  const todays = planner.tasks.filter((task) => task.planned_for === today && stateOf(task) !== "cancelled");
  const pending = todays.filter((task) => stateOf(task) === "pending");
  const finished = todays.length - pending.length;
  const ratio = todays.length > 0 ? finished / todays.length : 0;
  const focus = overdue[0] ?? pending[0] ?? null;
  const exam = planner.exams
    .filter((item) => item.days_left >= 0)
    .sort((a, b) => a.days_left - b.days_left)[0];

  const lateDays = focus && stateOf(focus) === "overdue" ? Math.max(1, Math.round((parseDay(today).getTime() - parseDay(focus.planned_for).getTime()) / 86_400_000)) : 0;
  const href = focus ? taskHref(focus) : null;
  const FocusIcon = focus ? (lateDays > 0 ? AlertTriangle : Target) : todays.length > 0 ? CheckCircle2 : PartyPopper;

  return (
    <section aria-labelledby="plan-focus" className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <div className="relative overflow-hidden rounded-card border border-border bg-surface p-5 shadow-card sm:p-6">
        <div aria-hidden className={`absolute inset-y-0 left-0 w-1 ${lateDays > 0 ? "bg-danger" : "bg-primary"}`} />
        <p id="plan-focus" className="text-[11px] font-semibold uppercase tracking-wider text-brand rtl:tracking-normal">
          {t("plx.focus.label")}
        </p>
        <div className="mt-3 flex items-start gap-4">
          <span
            className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl ${lateDays > 0 ? "bg-danger-soft text-danger" : "bg-primary-soft text-brand"}`}
          >
            <FocusIcon className="h-6 w-6" strokeWidth={1.75} aria-hidden />
          </span>
          <div className="min-w-0">
            {focus ? (
              <>
                <h2 className="font-display text-xl leading-snug sm:text-2xl">{taskTitle(focus, t)}</h2>
                <p className="mt-1 text-sm text-muted">
                  {lateDays > 0
                    ? t("plx.focus.lateBody", { count: lateDays, minutes: focus.minutes })
                    : t("plx.focus.body", { minutes: focus.minutes, course: focus.subject_name ?? t("course.none") })}
                </p>
              </>
            ) : todays.length > 0 ? (
              <>
                <h2 className="font-display text-xl leading-snug sm:text-2xl">{t("plx.focus.allDone")}</h2>
                <p className="mt-1 text-sm text-muted">{t("plx.focus.allDoneBody")}</p>
              </>
            ) : (
              <>
                <h2 className="font-display text-xl leading-snug sm:text-2xl">{t("pl.today.emptyTitle")}</h2>
                <p className="mt-1 text-sm text-muted">{t("plx.focus.emptyBody")}</p>
              </>
            )}
          </div>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-3">
          {focus ? (
            <>
              <Button size="lg" onClick={() => actions.onToggle(focus)}>
                <Check className="h-4 w-4" aria-hidden />
                {t("plx.focus.done")}
              </Button>
              {href ? (
                <ButtonLink href={href} variant="secondary" size="lg">
                  {t("plx.focus.open")}
                  <ArrowRight className="h-4 w-4 rtl:rotate-180" aria-hidden />
                </ButtonLink>
              ) : null}
            </>
          ) : todays.length === 0 ? (
            <Button size="lg" onClick={() => onAdd(today)}>
              <Plus className="h-4 w-4" aria-hidden />
              {t("pl.addTask")}
            </Button>
          ) : (
            <Link href="/quizzes" className="text-sm font-medium text-brand hover:underline">
              {t("plx.focus.more")}
            </Link>
          )}
          {todays.length > 0 ? (
            <span className="flex items-center gap-2 text-sm text-muted">
              <ProgressRing value={ratio} size={34} stroke={4} label={t("planner.today")}>
                <span className="tabular text-[10px] font-semibold text-ink">{Math.round(ratio * 100)}</span>
              </ProgressRing>
              {t("home.today.progress", { done: finished, total: todays.length })}
            </span>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Tile
          icon={ListChecks}
          label={t("plx.tile.today")}
          value={todays.length > 0 ? `${finished}/${todays.length}` : "—"}
          tone="bg-success-soft text-success"
        />
        <Tile
          icon={Clock}
          label={t("plx.tile.left")}
          value={pending.length > 0 ? t("plx.tile.leftValue", { minutes: loadOf(pending) }) : "—"}
          tone="bg-info-soft text-info"
        />
        <Tile
          icon={AlertTriangle}
          label={t("plx.tile.overdue")}
          value={overdue.length}
          tone={overdue.length > 0 ? "bg-danger-soft text-danger" : "bg-surface-3 text-muted"}
        />
        <Tile
          icon={GraduationCap}
          label={t("plx.tile.exam")}
          value={exam ? (exam.days_left === 0 ? t("plx.tile.examToday") : t("plx.tile.examValue", { days: exam.days_left })) : "—"}
          hint={exam ? undefined : t("plx.tile.noExam")}
          tone="bg-warning-soft text-warning"
        />
      </div>
    </section>
  );
}
