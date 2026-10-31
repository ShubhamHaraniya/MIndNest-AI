import {
  CalendarDays,
  Check,
  Flame,
  ClipboardCheck,
  FileText,
  FileUp,
  GraduationCap,
  ListChecks,
  MessageSquare,
  NotebookPen,
} from "lucide-react";
import Link from "next/link";

import { dueText, dueTone } from "@/components/dashboard/due";
import { KpiStrip, QuizTrend, StudyBars } from "@/components/dashboard/analytics";
import { Deadlines } from "@/components/dashboard/deadlines";
import { FocusCard } from "@/components/dashboard/focus-card";
import { nextStep } from "@/components/dashboard/home-hero";
import { Meter } from "@/components/dashboard/meter";
import { StudyTimeline } from "@/components/dashboard/timeline";
import { Badge } from "@/components/kit/badge";
import { ButtonLink } from "@/components/kit/button";
import { Panel, PanelLink } from "@/components/kit/panel";
import { EmptyState } from "@/components/kit/states";
import { Reveal } from "@/components/motion/reveal";
import type { MessageKey, TFunction } from "@/i18n/translate";
import { formatDay, parseDay, percent, relativeTime } from "@/lib/format";
import type { ActivityItem, DashboardData, DashCourse, MaterialKind, WeekDay } from "@/lib/types";

const KIND_KEYS: Record<string, MessageKey> = {
  material: "wb.kind.material",
  past_paper: "wb.kind.past_paper",
  note: "wb.kind.note",
  assignment: "wb.kind.assignment",
};

// ---------------------------------------------------------------------------- course strip

function CourseStrip({ course, t, locale }: { course: DashCourse; t: TFunction; locale: string }) {
  const exam =
    course.next_exam_title && course.next_exam_days !== null
      ? t("wb.course.examIn", { title: course.next_exam_title, when: dueText(t, course.next_exam_days) })
      : t("wb.course.noExam");
  const facts: { label: string; value: string; warn?: boolean }[] = [
    {
      label: t("wb.course.documents"),
      value: `${course.documents}${course.documents > 0 ? ` (${t("wb.course.ready", { ready: course.documents_ready })})` : ""}`,
    },
    { label: t("wb.course.papers"), value: String(course.past_papers) },
    { label: t("wb.course.notes"), value: String(course.notes) },
    {
      label: t("wb.course.quizzes"),
      value: course.quiz_attempts > 0 ? `${course.quiz_attempts} · ${percent(course.quiz_average)}` : "0",
    },
    { label: t("wb.course.chats"), value: String(course.chats) },
    {
      label: t("wb.course.exam"),
      value: exam,
      warn: course.next_exam_days !== null && course.next_exam_days <= 7,
    },
  ];

  return (
    <section aria-labelledby="course-title" className="glass sheen rounded-card">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 px-3.5 py-3">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">
            {t("course.label")}
          </p>
          <h2 id="course-title" className="font-display mt-0.5 truncate text-xl leading-tight">
            {course.name}
          </h2>
          <p className="mt-0.5 text-xs text-muted">
            {[course.course_code, course.semester].filter(Boolean).join(" · ")}
            {course.course_code || course.semester ? " · " : ""}
            {course.last_activity_at
              ? t("wb.course.lastActive", { when: relativeTime(course.last_activity_at, locale) })
              : t("wb.course.noActivity")}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ButtonLink href="/chat" size="sm">
            <MessageSquare className="h-3.5 w-3.5" aria-hidden />
            {t("wb.course.ask")}
          </ButtonLink>
          <ButtonLink href="/quizzes" size="sm" variant="secondary">
            <ListChecks className="h-3.5 w-3.5" aria-hidden />
            {t("wb.course.quiz")}
          </ButtonLink>
          <ButtonLink href={course.id ? `/subjects/${course.id}` : "/subjects"} size="sm" variant="secondary">
            <FileUp className="h-3.5 w-3.5" aria-hidden />
            {course.id ? t("wb.course.open") : t("dbx.allCourses.open")}
          </ButtonLink>
        </div>
      </div>
      <dl className="grid grid-cols-2 border-t border-border sm:grid-cols-3 lg:grid-cols-6">
        {facts.map((fact, index) => (
          <div
            key={fact.label}
            className={`min-w-0 px-3.5 py-2 ${index > 0 ? "lg:border-l lg:border-border" : ""} ${
              index % 2 === 1 ? "border-l border-border sm:border-l-0" : ""
            } ${index % 3 !== 0 ? "sm:border-l sm:border-border" : "sm:border-l-0"} ${index >= 2 ? "border-t border-border lg:border-t-0" : ""}`}
          >
            <dt className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{fact.label}</dt>
            <dd className={`tabular truncate text-[14px] ${fact.warn ? "font-medium text-warning" : ""}`}>{fact.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

// ------------------------------------------------------------------------------ week ahead

function WeekRow({
  day,
  scale,
  daily,
  isToday,
  t,
  locale,
}: {
  day: WeekDay;
  scale: number;
  daily: number;
  isToday: boolean;
  t: TFunction;
  locale: string;
}) {
  const over = day.minutes_planned - daily;
  const overloaded = over > 0 && !day.day_off;
  const conflict = day.day_off && day.tasks > 0;
  const donePct = (day.minutes_done / scale) * 100;
  const restPct = ((day.minutes_planned - day.minutes_done) / scale) * 100;
  return (
    <li className="grid grid-cols-[3.75rem_minmax(0,1fr)] items-center gap-x-3 gap-y-1 px-3.5 py-2 sm:grid-cols-[4.5rem_minmax(0,1fr)_minmax(0,11rem)]">
      <div>
        <p className={`text-[13px] leading-4 ${isToday ? "font-semibold text-brand" : "font-medium"}`}>
          {isToday ? t("wb.week.today") : formatDay(day.date, locale, { weekday: "short" })}
        </p>
        <p className="text-xs text-faint">{formatDay(day.date, locale, { day: "numeric", month: "short" })}</p>
      </div>
      <div
        role="img"
        aria-label={t("wb.week.planned", { planned: day.minutes_planned, done: day.minutes_done })}
        className="relative h-2.5 rounded-full bg-surface-3"
      >
        <div className="absolute inset-y-0 left-0 flex overflow-hidden rounded-full" style={{ width: `${Math.min(100, donePct + restPct)}%` }}>
          <span className="h-full bg-gradient-to-r from-primary to-accent" style={{ width: `${(donePct / Math.max(donePct + restPct, 0.0001)) * 100}%` }} />
          <span
            className={`h-full flex-1 ${overloaded || conflict ? "bg-warning/60" : "bg-border-strong"}`}
          />
        </div>
        <span
          aria-hidden
          className="absolute -inset-y-0.5 w-px bg-ink/70"
          style={{ left: `${Math.min(100, (daily / scale) * 100)}%` }}
        />
      </div>
      <div className="col-span-2 flex min-w-0 flex-wrap items-center gap-1 sm:col-span-1 sm:justify-end">
        {day.markers.map((marker, index) => (
          <Badge key={`${marker.kind}-${index}`} tone={marker.kind === "exam" ? "danger" : "warning"} className="max-w-full">
            <span className="truncate">
              {t(marker.kind === "exam" ? "wb.week.exam" : "wb.week.due")} · {marker.title}
            </span>
          </Badge>
        ))}
        {day.day_off ? <span className="text-xs text-faint">{t("wb.week.dayOff")}</span> : null}
        {overloaded ? <span className="tabular text-xs font-medium text-warning">{t("wb.week.over", { minutes: over })}</span> : null}
        {!day.day_off && !overloaded && day.markers.length === 0 ? (
          <span className="tabular text-xs text-muted">
            {day.minutes_planned > 0 ? `${day.minutes_planned} ${t("dashboard.minShort")}` : t("wb.week.free")}
          </span>
        ) : null}
      </div>
    </li>
  );
}

function WeekAhead({ data, t, locale }: { data: DashboardData; t: TFunction; locale: string }) {
  const scale = Math.max(data.daily_minutes, ...data.week.map((day) => day.minutes_planned), 1) * 1.05;
  return (
    <Panel
      id="week"
      title={t("wb.week.title")}
      description={t("wb.week.target", { minutes: data.daily_minutes })}
      action={<PanelLink href="/planner">{t("wb.today.openPlanner")}</PanelLink>}
    >
      <ul className="divide-y divide-border">
        {data.week.map((day) => (
          <WeekRow
            key={day.date}
            day={day}
            scale={scale}
            daily={data.daily_minutes}
            isToday={day.date === data.today}
            t={t}
            locale={locale}
          />
        ))}
      </ul>
    </Panel>
  );
}

// -------------------------------------------------------------------------------- documents shelf

function RecentDocuments({ data, t, locale }: { data: DashboardData; t: TFunction; locale: string }) {
  const docs = data.recent_documents;
  return (
    <Panel
      id="docs"
      title={t("wb.docs.title")}
      className="h-full"
      action={<PanelLink href="/subjects">{t("wb.panel.viewAll")}</PanelLink>}
    >
      {docs.length === 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-6">
          <p className="text-sm text-muted">{t("wb.docs.empty")}</p>
          {data.course ? (
            <ButtonLink href={`/subjects/${data.course.id}`} size="sm" variant="secondary">
              <FileUp className="h-3.5 w-3.5" aria-hidden />
              {t("wb.docs.upload")}
            </ButtonLink>
          ) : null}
        </div>
      ) : (
        <ul className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
          {docs.slice(0, 6).map((doc) => (
            <li key={doc.id}>
              <Link
                href={`/subjects/${doc.subject_id}?doc=${doc.id}`}
                className="glass-flat card-hover group flex h-full flex-col gap-3 rounded-2xl p-3.5"
              >
                <span className="flex items-start justify-between gap-2">
                  <span className="flex h-10 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-brand ring-1 ring-primary/20">
                    <FileText className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />
                  </span>
                  <span className="flex flex-wrap justify-end gap-1">
                    <Badge>{t(KIND_KEYS[doc.kind as MaterialKind] ?? "wb.kind.material")}</Badge>
                    {doc.status !== "ready" ? (
                      <Badge tone={doc.status === "failed" ? "danger" : "info"}>{t(`materials.status.${doc.status}`)}</Badge>
                    ) : null}
                  </span>
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-[13px] font-medium group-hover:text-brand">{doc.filename}</span>
                  <span className="block truncate text-xs text-muted">{[doc.subject_name, doc.module].filter(Boolean).join(" · ")}</span>
                </span>
                <span className="mt-auto text-[11px] text-faint">
                  {t(doc.reason === "opened" ? "wb.docs.opened" : "wb.docs.added", { when: relativeTime(doc.at, locale) })}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

// ------------------------------------------------------------------------------ right column

function AssignmentsDue({ data, t, locale }: { data: DashboardData; t: TFunction; locale: string }) {
  return (
    <Panel
      id="due"
      title={t("wb.due.title")}
      action={<PanelLink href="/assignments">{t("wb.due.all")}</PanelLink>}
    >
      {data.assignments_due.length === 0 ? (
        <p className="px-3.5 py-4 text-sm text-muted">{t("wb.due.empty")}</p>
      ) : (
        <ul className="divide-y divide-border">
          {data.assignments_due.map((item) => (
            <li key={item.id}>
              <Link href={`/assignments/${item.id}`} className="flex items-center gap-3 px-3.5 py-2 hover:bg-surface-3/50">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium">{item.title}</p>
                  <p className="truncate text-xs text-muted">
                    {[item.subject_name, t(item.status === "in_progress" ? "wb.due.in_progress" : "wb.due.todo")].filter(Boolean).join(" · ")}
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  <Badge tone={dueTone(item.days_left)}>{dueText(t, item.days_left)}</Badge>
                  <p className="mt-0.5 text-[11px] text-faint">
                    {formatDay(item.due_on, locale, { day: "numeric", month: "short" })}
                  </p>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function WeakTopics({ data, t }: { data: DashboardData; t: TFunction }) {
  return (
    <Panel
      id="weak"
      title={t("wb.weak.title")}
      description={data.course?.name}
      action={<PanelLink href="/quizzes">{t("wb.weak.practise")}</PanelLink>}
    >
      {data.weak_topics.length === 0 ? (
        <p className="px-3.5 py-4 text-sm text-muted">{t("wb.weak.empty")}</p>
      ) : (
        <ul className="divide-y divide-border">
          {data.weak_topics.map((topic) => (
            <li key={`${topic.subject_id}-${topic.material}`} className="px-3.5 py-2">
              <div className="flex items-baseline justify-between gap-3">
                <p className="truncate text-[13px] font-medium">{topic.material}</p>
                <span className="tabular shrink-0 text-[13px] font-semibold text-danger">{percent(topic.accuracy)}</span>
              </div>
              <div className="mt-1 flex items-center gap-3">
                <Meter value={topic.accuracy} tone="danger" label={t("dashboard.accuracyLabel", { name: topic.material })} className="flex-1" />
                <span className="tabular text-xs text-muted">{t("wb.weak.answers", { count: topic.answers })}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

const ACTIVITY_ICONS = {
  chat: MessageSquare,
  quiz: ListChecks,
  material: FileUp,
  task: ClipboardCheck,
  assignment: NotebookPen,
} as const;

function activityLabel(t: TFunction, item: ActivityItem): string {
  if (item.kind === "quiz") return t("wb.activity.quiz", { score: item.detail ?? "—" });
  const keys = {
    chat: "wb.activity.chat",
    material: "wb.activity.material",
    task: "wb.activity.task",
    assignment: "wb.activity.assignment",
  } as const;
  return t(keys[item.kind]);
}

function Activity({ data, t, locale }: { data: DashboardData; t: TFunction; locale: string }) {
  return (
    <Panel id="activity" title={t("wb.activity.title")}>
      {data.activity.length === 0 ? (
        <p className="px-3.5 py-4 text-sm text-muted">{t("wb.activity.empty")}</p>
      ) : (
        <ol className="divide-y divide-border">
          {data.activity.slice(0, 8).map((item, index) => {
            const Icon = ACTIVITY_ICONS[item.kind];
            return (
              <li key={`${item.kind}-${item.href}-${index}`}>
                <Link href={item.href} className="flex items-start gap-2.5 px-3.5 py-2 hover:bg-surface-3/50">
                  <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-faint" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px]">{item.title}</p>
                    <p className="truncate text-xs text-muted">
                      {[activityLabel(t, item), item.subject_name].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                  <time dateTime={item.at} className="shrink-0 text-[11px] text-faint">
                    {relativeTime(item.at, locale)}
                  </time>
                </Link>
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}

// ------------------------------------------------------------------------------ getting started

const SETUP_KEYS: Record<string, MessageKey> = {
  course: "dbx.setup.course",
  material: "dbx.setup.material",
  institution: "dbx.setup.institution",
  provider: "dbx.setup.provider",
  chat: "dbx.setup.chat",
  quiz: "dbx.setup.quiz",
};

/** A short checklist for a new account, ticked from real data; it disappears once the four
 *  basics (course, material, college, AI key) are done. */
function GettingStarted({ setup, t }: { setup: NonNullable<DashboardData["setup"]>; t: TFunction }) {
  return (
    <Panel id="setup" title={t("dbx.setup.title")} description={t("dbx.setup.progress", { done: setup.done, total: setup.total })}>
      <ul className="divide-y divide-border">
        {setup.steps.map((step) => (
          <li key={step.key}>
            <Link href={step.href} className="flex items-center gap-3 px-3.5 py-2 text-[13px] hover:bg-surface-3/50">
              <span
                aria-hidden
                className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-sm border ${
                  step.done ? "border-primary bg-primary text-on-primary" : "border-border-strong bg-surface"
                }`}
              >
                {step.done ? <Check className="h-3 w-3" /> : null}
              </span>
              <span className={step.done ? "text-faint line-through" : ""}>{t(SETUP_KEYS[step.key] ?? "dbx.setup.course")}</span>
              <span className="sr-only">{step.done ? t("dbx.setup.done") : t("dbx.setup.todo")}</span>
            </Link>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// ------------------------------------------------------------------------------------- page

export function Workbench({ data, name, t, locale }: { data: DashboardData; name: string; t: TFunction; locale: string }) {
  const today = parseDay(data.today);
  // With no course chosen the page is about every course: show their combined figures, and the
  // "create your first course" prompt only when there really is no course.
  const overview = data.overview;
  const everything: DashCourse | null =
    !data.course && overview && data.stats.subjects > 0
      ? {
          id: "",
          name: t("course.none"),
          course_code: null,
          semester: t("dbx.allCourses.count", { count: overview.courses }),
          documents: overview.documents,
          documents_ready: overview.documents_ready,
          past_papers: overview.past_papers,
          notes: overview.notes,
          quiz_attempts: overview.quiz_attempts,
          quiz_average: overview.quiz_average,
          last_activity_at: overview.last_activity_at,
          next_exam_title: overview.next_exam_title,
          next_exam_on: overview.next_exam_on,
          next_exam_days: overview.next_exam_days,
          chats: overview.chats,
        }
      : null;
  const step = nextStep(data, t);
  const StepIcon = step.icon;
  const streakText = data.streak_days > 0 ? t("dashboard.streak", { count: data.streak_days }) : t("dashboard.streakStart");

  return (
    <div className="space-y-5">
      {/* A greeting row with the day, the streak and two quick doors. */}
      <Reveal as="header" className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-sm text-muted">
            <CalendarDays className="h-4 w-4" aria-hidden />
            {today.toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "long" })}
          </p>
          <h1 className="font-display mt-1.5 truncate text-3xl leading-tight sm:text-4xl">
            <span className="bg-gradient-to-br from-ink via-ink to-brand bg-clip-text text-transparent">{t("dashboard.welcomeBack", { name })}</span>
          </h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="glass inline-flex h-10 items-center gap-2 rounded-full px-4 text-sm">
            <Flame className="h-4 w-4 text-warning" aria-hidden />
            {streakText}
          </span>
          <ButtonLink href="/chat" size="md">
            <MessageSquare className="h-4 w-4" aria-hidden />
            {t("dashboard.qaChat")}
          </ButtonLink>
          <ButtonLink href="/quizzes" size="md" variant="secondary">
            <ListChecks className="h-4 w-4" aria-hidden />
            {t("dashboard.qaQuiz")}
          </ButtonLink>
        </div>
      </Reveal>

      {data.setup?.show ? <GettingStarted setup={data.setup} t={t} /> : null}

      {/* The command row: what to do now, and today's timeline. */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <FocusCard
          icon={<StepIcon strokeWidth={1.75} aria-hidden />}
          title={step.title}
          body={step.body}
          cta={step.cta}
          href={step.href}
          done={data.today_tasks.done}
          total={data.today_tasks.total}
          minutesDone={data.today_tasks.minutes_done}
          minutesTotal={data.today_tasks.minutes_total}
        />
        <StudyTimeline tasks={data.schedule} dailyMinutes={data.daily_minutes} revisionDue={data.stats.revision_due} />
      </div>

      <KpiStrip data={data} />

      {/* Performance: study time, quiz scores and what is coming up. */}
      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <StudyBars week={data.study_week} today={data.today} />
        <QuizTrend trend={data.quiz_trend} />
        <div className="lg:col-span-2 xl:col-span-1">
          <Deadlines items={data.deadlines} />
        </div>
      </div>

      {data.course || everything ? (
        <Reveal>
          <CourseStrip course={(data.course ?? everything) as DashCourse} t={t} locale={locale} />
        </Reveal>
      ) : (
        <EmptyState icon={<GraduationCap className="h-[18px] w-[18px]" aria-hidden />} title={t("wb.start.title")} description={t("wb.start.body")}>
          <ButtonLink href="/subjects?new=1">{t("wb.start.cta")}</ButtonLink>
        </EmptyState>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-4">
          <WeekAhead data={data} t={t} locale={locale} />
          <RecentDocuments data={data} t={t} locale={locale} />
        </div>
        <div className="min-w-0 space-y-4">
          <AssignmentsDue data={data} t={t} locale={locale} />
          <WeakTopics data={data} t={t} />
          <Activity data={data} t={t} locale={locale} />
        </div>
      </div>
    </div>
  );
}
