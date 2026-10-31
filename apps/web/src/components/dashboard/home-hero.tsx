import { ArrowRight, BookOpenCheck, ClipboardList, Flame, MessageSquare, Rocket, Target, Trophy, Layers } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { dueText } from "@/components/dashboard/due";
import { ButtonLink } from "@/components/kit/button";
import { ProgressRing } from "@/components/kit/progress";
import type { MessageKey, TFunction } from "@/i18n/translate";
import { percent } from "@/lib/format";
import type { DashboardData } from "@/lib/types";

const SETUP_KEYS: Record<string, MessageKey> = {
  course: "dbx.setup.course",
  material: "dbx.setup.material",
  institution: "dbx.setup.institution",
  provider: "dbx.setup.provider",
  chat: "dbx.setup.chat",
  quiz: "dbx.setup.quiz",
};

type Step = { icon: LucideIcon; title: string; body: string; cta: string; href: string };

/** The one thing worth doing next, worked out from the student's real data, in this order:
 *  finish setting up, today's first open task, cards due, an assignment due within three days,
 *  and otherwise a question about their notes. */
export function nextStep(data: DashboardData, t: TFunction): Step {
  const open = data.setup?.show ? data.setup.steps.find((step) => !step.done) : undefined;
  if (open) {
    return {
      icon: Rocket,
      title: t("home.next.setup", { step: t(SETUP_KEYS[open.key] ?? "dbx.setup.course") }),
      body: t("home.next.setupBody"),
      cta: t("home.next.setupCta"),
      href: open.href,
    };
  }
  const task = data.schedule.find((item) => item.status === "todo" && item.state !== "cancelled");
  if (task) {
    return {
      icon: Target,
      title: task.title,
      body: t("home.next.taskBody", { minutes: task.minutes, course: task.subject_name ?? t("course.none") }),
      cta: t("home.next.taskCta"),
      href: task.href ?? "/planner",
    };
  }
  if (data.stats.revision_due > 0) {
    return {
      icon: Layers,
      title: t("home.next.cards", { count: data.stats.revision_due }),
      body: t("home.next.cardsBody"),
      cta: t("home.next.cardsCta"),
      href: "/quizzes",
    };
  }
  const assignment = data.assignments_due.find((item) => item.days_left <= 3);
  if (assignment) {
    return {
      icon: ClipboardList,
      title: t("home.next.assignment", { title: assignment.title, when: dueText(t, assignment.days_left) }),
      body: t("home.next.assignmentBody"),
      cta: t("home.next.assignmentCta"),
      href: `/assignments/${assignment.id}`,
    };
  }
  return {
    icon: MessageSquare,
    title: t("home.next.ask"),
    body: t("home.next.askBody"),
    cta: t("home.next.askCta"),
    href: "/chat",
  };
}

export function Tile({ icon: Icon, label, value, hint, tone }: { icon: LucideIcon; label: string; value: ReactNode; hint?: string; tone: string }) {
  return (
    <div className="flex items-center gap-3 rounded-card border border-border bg-surface px-4 py-3 shadow-card">
      <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${tone}`}>
        <Icon className="h-5 w-5" strokeWidth={1.75} aria-hidden />
      </span>
      <div className="min-w-0">
        <p className="tabular truncate text-xl font-semibold leading-6">{value}</p>
        <p className="truncate text-xs text-muted">{hint ? `${label} · ${hint}` : label}</p>
      </div>
    </div>
  );
}

/** The top of Home: the next step as one clear card, with four small figures beside it. */
export function HomeHero({ data, t }: { data: DashboardData; t: TFunction }) {
  const step = nextStep(data, t);
  const Icon = step.icon;
  const { total, done } = data.today_tasks;
  const ratio = total > 0 ? done / total : 0;

  return (
    <section aria-labelledby="next-step" className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
      <div className="relative overflow-hidden rounded-card border border-border bg-surface p-5 shadow-card sm:p-6">
        <div aria-hidden className="absolute inset-y-0 left-0 w-1 bg-primary" />
        <p id="next-step" className="text-[11px] font-semibold uppercase tracking-wider text-brand rtl:tracking-normal">
          {t("home.next.label")}
        </p>
        <div className="mt-3 flex items-start gap-4">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-primary-soft text-brand">
            <Icon className="h-6 w-6" strokeWidth={1.75} aria-hidden />
          </span>
          <div className="min-w-0">
            <h2 className="font-display text-xl leading-snug sm:text-2xl">{step.title}</h2>
            <p className="mt-1 text-sm text-muted">{step.body}</p>
          </div>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <ButtonLink href={step.href} size="lg">
            {step.cta}
            <ArrowRight className="h-4 w-4 rtl:rotate-180" aria-hidden />
          </ButtonLink>
          {total > 0 ? (
            <span className="flex items-center gap-2 text-sm text-muted">
              <ProgressRing value={ratio} size={34} stroke={4} label={t("home.kpi.today")}>
                <span className="tabular text-[10px] font-semibold text-ink">{Math.round(ratio * 100)}</span>
              </ProgressRing>
              {t("home.today.progress", { done, total })}
            </span>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Tile
          icon={Flame}
          label={t("home.kpi.streak")}
          value={data.streak_days}
          hint={data.streak_days === 0 ? t("home.kpi.streakStart") : undefined}
          tone="bg-warning-soft text-warning"
        />
        <Tile
          icon={BookOpenCheck}
          label={t("home.kpi.today")}
          value={total > 0 ? `${done}/${total}` : "—"}
          tone="bg-success-soft text-success"
        />
        <Tile icon={Layers} label={t("home.kpi.cards")} value={data.stats.revision_due} tone="bg-info-soft text-info" />
        <Tile icon={Trophy} label={t("home.kpi.quiz")} value={percent(data.stats.quiz_average)} tone="bg-primary-soft text-brand" />
      </div>
    </section>
  );
}
