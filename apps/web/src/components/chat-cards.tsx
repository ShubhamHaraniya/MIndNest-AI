"use client";

import clsx from "clsx";
import {
  AlertCircle,
  BookOpen,
  CalendarClock,
  CalendarPlus,
  CalendarX,
  CheckCircle2,
  Circle,
  ClipboardList,
  Download,
  ExternalLink,
  FileText,
  Loader2,
  Play,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { Markdown } from "@/components/markdown";
import { Button, Field } from "@/components/ui";
import { useLocale, useT } from "@/i18n/client";
import type { MessageKey } from "@/i18n/translate";
import { ApiError, api } from "@/lib/api";
import { isWorking, failureText as runFailure } from "@/lib/assignments";
import { beginAttempt, failureText as quizFailure, isWriting } from "@/lib/quiz";
import { errorMessage } from "@/lib/errors";
import type {
  AssignmentRun,
  CalendarEdits,
  CalendarEventDraft,
  CalendarEventView,
  CalendarProposal,
  ChatCard,
  Quiz,
} from "@/lib/types";

const noop = () => undefined;

/** Ask `tick` again every `everyMs` until it says it is finished (or `maxTries` is used up). */
function usePolling(tick: () => Promise<boolean>, everyMs: number, maxTries: number) {
  const latest = useRef(tick);
  latest.current = tick;
  useEffect(() => {
    let stopped = false;
    let tries = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      if (stopped) return;
      let finished = false;
      try {
        finished = await latest.current();
      } catch {
        // A hiccup is not the end: try again until the tries run out.
      }
      tries += 1;
      if (!finished && !stopped && tries < maxTries) timer = setTimeout(run, everyMs);
    };
    void run();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [everyMs, maxTries]);
}

function Shell({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <section className="glass-flat mt-3 rounded-2xl p-4 text-sm">
      <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted">
        {icon}
        <span className="truncate">{title}</span>
      </h3>
      {children}
    </section>
  );
}

const ICON = "h-4 w-4 shrink-0";

/** Answer a calendar proposal. Resolves when the rest of the answer has finished streaming. */
export type DecideFn = (runId: string, decision: "approve" | "reject", edits?: CalendarEdits) => Promise<void>;

export function ChatCards({ cards, onDecide, busy = false }: { cards: ChatCard[]; onDecide?: DecideFn; busy?: boolean }) {
  return (
    <>
      {cards.map((card, index) => {
        const key = `${card.kind}-${index}`;
        switch (card.kind) {
          case "quiz":
            return <QuizCard key={key} data={card.data} />;
          case "quiz_attempt":
            return <AttemptCard key={key} data={card.data} />;
          case "materials":
            return <MaterialsCard key={key} data={card.data} />;
          case "material":
            return <MaterialCard key={key} data={card.data} />;
          case "exam":
            return <ExamCard key={key} data={card.data} />;
          case "plan":
            return <PlanCard key={key} data={card.data} />;
          case "assignment":
            return <AssignmentCard key={key} data={card.data} />;
          case "assignment_run":
            return <RunCard key={key} data={card.data} />;
          case "calendar_proposal":
            return <CalendarProposalCard key={key} data={card.data} onDecide={onDecide} busy={busy} />;
          case "calendar_events":
            return <CalendarEventsCard key={key} data={card.data} />;
          case "calendar_connect":
            return <CalendarConnectCard key={key} data={card.data} />;
          default:
            return null; // a card from a newer server: ignored
        }
      })}
    </>
  );
}

// ---------------------------------------------------------------------------------------- quiz

function QuizCard({ data }: { data: Extract<ChatCard, { kind: "quiz" }>["data"] }) {
  const t = useT();
  const router = useRouter();
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [gone, setGone] = useState(false);
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  usePolling(
    async () => {
      try {
        const current = await api<Quiz>(`/quizzes/${data.quiz_id}`);
        setQuiz(current);
        return !isWriting(current.status);
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 404) {
          setGone(true);
          return true;
        }
        throw caught;
      }
    },
    2500,
    120,
  );

  async function start() {
    setStarting(true);
    setProblem(null);
    try {
      router.push(`/quizzes/attempt/${await beginAttempt(data.quiz_id)}`);
    } catch {
      setProblem(t("errors.generic"));
      setStarting(false);
    }
  }

  const status = quiz?.status ?? "queued";
  const basisKey: MessageKey =
    data.basis === "notes" ? "chat.card.quiz.notes" : data.basis === "revision" ? "chat.card.quiz.revision" : "chat.card.quiz.general";

  return (
    <Shell icon={<ClipboardList className={ICON} aria-hidden />} title={t("chat.card.quiz.title")}>
      <p className="font-medium">{quiz?.title ?? data.title}</p>
      <p className={clsx("mt-0.5 text-xs", data.basis === "general" ? "font-medium text-warning" : "text-muted")}>
        {t(basisKey)}
      </p>
      {gone ? (
        <p className="mt-2 text-xs text-muted">{t("chat.card.gone")}</p>
      ) : status === "failed" ? (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-danger">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {quizFailure(quiz?.error ?? null, t)}
        </p>
      ) : isWriting(status) ? (
        <p className="mt-2 flex items-center gap-2 text-xs text-muted" role="status">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          {t("chat.card.quiz.writing")}
        </p>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted">{t("chat.card.quiz.ready", { n: quiz?.question_count ?? data.count })}</span>
          <Button onClick={() => void start()} loading={starting} className="px-3 py-1.5 text-xs">
            <Play className="h-3.5 w-3.5" aria-hidden />
            {t("chat.card.quiz.start")}
          </Button>
          <Link href={`/quizzes/${data.quiz_id}`} className="text-xs text-primary hover:underline">
            {t("chat.card.quiz.open")}
          </Link>
        </div>
      )}
      {problem ? <p className="mt-2 text-xs text-danger">{problem}</p> : null}
    </Shell>
  );
}

function AttemptCard({ data }: { data: Extract<ChatCard, { kind: "quiz_attempt" }>["data"] }) {
  const t = useT();
  return (
    <Shell icon={<Play className={ICON} aria-hidden />} title={t("chat.card.attempt.title")}>
      <Link
        href={`/quizzes/attempt/${data.attempt_id}`}
        className="inline-flex rounded bg-primary px-3 py-1.5 text-xs font-medium text-on-primary hover:bg-primary-hover"
      >
        {t("chat.card.attempt.continue")}
      </Link>
    </Shell>
  );
}

// ------------------------------------------------------------------------------------ materials

function statusLabel(status: string, t: (key: MessageKey) => string): string {
  return ["uploaded", "processing", "ready", "failed"].includes(status) ? t(`materials.status.${status}` as MessageKey) : status;
}

function MaterialsCard({ data }: { data: Extract<ChatCard, { kind: "materials" }>["data"] }) {
  const t = useT();
  return (
    <Shell icon={<FileText className={ICON} aria-hidden />} title={t("chat.card.materials.title")}>
      <ul className="space-y-1.5">
        {data.items.map((item) => (
          <li key={item.id} className="flex items-center gap-2">
            <span className="min-w-0 flex-1">
              <span className="block truncate">{item.filename}</span>
              <span className="block truncate text-xs text-muted">
                {item.subject}
                {item.status !== "ready" ? ` · ${statusLabel(item.status, t)}` : ""}
              </span>
            </span>
            {item.status === "ready" ? (
              <a
                href={`/api/v1/materials/${item.id}/download`}
                aria-label={t("chat.openFile")}
                className="shrink-0 rounded p-1.5 text-primary hover:bg-primary-soft"
              >
                <Download className="h-4 w-4" aria-hidden />
              </a>
            ) : null}
          </li>
        ))}
      </ul>
      {data.total > data.items.length ? (
        <p className="mt-2 text-xs text-muted">{t("chat.card.more", { n: data.total - data.items.length })}</p>
      ) : null}
    </Shell>
  );
}

function MaterialCard({ data }: { data: Extract<ChatCard, { kind: "material" }>["data"] }) {
  const t = useT();
  return (
    <Shell icon={<BookOpen className={ICON} aria-hidden />} title={t("chat.card.material.title")}>
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{data.filename}</span>
          <span className="block truncate text-xs text-muted">{data.subject}</span>
        </span>
        <a
          href={`/api/v1/materials/${data.id}/download`}
          className="flex shrink-0 items-center gap-1 text-xs text-primary hover:underline"
        >
          <Download className="h-3.5 w-3.5" aria-hidden />
          {t("chat.openFile")}
        </a>
      </div>
    </Shell>
  );
}

// ------------------------------------------------------------------------------------- planner

function dayLabel(day: string, locale: string): string {
  const date = new Date(`${day}T12:00:00`);
  return Number.isNaN(date.getTime())
    ? day
    : date.toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" });
}

function ExamCard({ data }: { data: Extract<ChatCard, { kind: "exam" }>["data"] }) {
  const t = useT();
  const locale = useLocale();
  return (
    <Shell icon={<CalendarClock className={ICON} aria-hidden />} title={t("chat.card.exam.title")}>
      <p className="font-medium">{data.title}</p>
      <p className="mt-0.5 text-xs text-muted">
        {dayLabel(data.exam_on, locale)}
        {" · "}
        {data.days_left <= 0 ? t("chat.card.exam.today") : t("chat.card.exam.daysLeft", { n: data.days_left })}
        {data.subject ? ` · ${data.subject}` : ""}
      </p>
      <Link href="/planner" className="mt-2 inline-block text-xs text-primary hover:underline">
        {t("chat.card.plan.open")}
      </Link>
    </Shell>
  );
}

function PlanCard({ data }: { data: Extract<ChatCard, { kind: "plan" }>["data"] }) {
  const t = useT();
  const locale = useLocale();
  const days: { day: string; items: typeof data.items }[] = [];
  for (const item of data.items) {
    const last = days[days.length - 1];
    if (last && last.day === item.day) last.items.push(item);
    else days.push({ day: item.day, items: [item] });
  }
  return (
    <Shell icon={<CalendarClock className={ICON} aria-hidden />} title={t("chat.card.plan.title")}>
      <ul className="space-y-2">
        {days.map(({ day, items }) => (
          <li key={day}>
            <p className="text-xs font-medium text-muted">{dayLabel(day, locale)}</p>
            <ul className="mt-1 space-y-1">
              {items.map((item) => (
                <li key={item.id} className="flex items-start gap-2">
                  {item.status === "done" ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
                  ) : (
                    <Circle className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden />
                  )}
                  <span className={clsx("min-w-0 flex-1", item.status !== "todo" && "text-muted line-through")}>
                    {item.title}
                    {item.subject ? <span className="text-muted"> · {item.subject}</span> : null}
                  </span>
                  <span className="shrink-0 text-xs text-muted">{t("chat.card.plan.minutes", { n: item.minutes })}</span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      {data.total > data.items.length ? (
        <p className="mt-2 text-xs text-muted">{t("chat.card.more", { n: data.total - data.items.length })}</p>
      ) : null}
      <Link href="/planner" className="mt-2 inline-block text-xs text-primary hover:underline">
        {t("chat.card.plan.open")}
      </Link>
    </Shell>
  );
}

// --------------------------------------------------------------------------------- assignments

function AssignmentCard({ data }: { data: Extract<ChatCard, { kind: "assignment" }>["data"] }) {
  const t = useT();
  const locale = useLocale();
  const due = data.due_at
    ? new Date(data.due_at).toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric" })
    : null;
  const known = ["todo", "in_progress", "done"].includes(data.status);
  return (
    <Shell icon={<ClipboardList className={ICON} aria-hidden />} title={t("chat.card.assignment.title")}>
      <p className="font-medium">{data.title}</p>
      <p className="mt-0.5 text-xs text-muted">
        {known ? t(`assign.status.${data.status}` as MessageKey) : data.status}
        {due ? ` · ${t("chat.card.assignment.due", { date: due })}` : ""}
        {data.subject ? ` · ${data.subject}` : ""}
      </p>
      <Link href={`/assignments/${data.id}`} className="mt-2 inline-block text-xs text-primary hover:underline">
        {t("chat.card.assignment.open")}
      </Link>
    </Shell>
  );
}

function RunCard({ data }: { data: Extract<ChatCard, { kind: "assignment_run" }>["data"] }) {
  const t = useT();
  const [run, setRun] = useState<AssignmentRun | null>(null);
  const [gone, setGone] = useState(false);

  usePolling(
    async () => {
      try {
        const current = await api<AssignmentRun>(`/assignments/${data.assignment_id}/runs/${data.run_id}`);
        setRun(current);
        return !isWorking(current.status);
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 404) {
          setGone(true);
          return true;
        }
        throw caught;
      }
    },
    2500,
    120,
  );

  const kinds = ["breakdown", "outline", "feedback"];
  const kindLabel = kinds.includes(data.kind) ? t(`chat.card.run.${data.kind}` as MessageKey) : data.kind;
  const working = !run || isWorking(run.status);

  return (
    <Shell icon={<ClipboardList className={ICON} aria-hidden />} title={`${kindLabel} · ${data.title}`}>
      {gone ? (
        <p className="text-xs text-muted">{t("chat.card.gone")}</p>
      ) : run?.status === "failed" ? (
        <p className="flex items-start gap-1.5 text-xs text-danger">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {runFailure(run.error, t)}
        </p>
      ) : working ? (
        <p className="flex items-center gap-2 text-xs text-muted" role="status">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          {t("chat.card.run.writing", { kind: kindLabel.toLowerCase() })}
        </p>
      ) : run?.result ? (
        <div className="rounded-xl bg-surface-2/60 p-3">
          <Markdown text={run.result} citations={[]} streaming={false} onCite={noop} />
        </div>
      ) : null}
      <Link href={`/assignments/${data.assignment_id}`} className="mt-2 inline-block text-xs text-primary hover:underline">
        {t("chat.card.assignment.open")}
      </Link>
    </Shell>
  );
}

// ------------------------------------------------------------------------------------ calendar

function whenText(
  event: { day: string; start_time: string; minutes: number; all_day: boolean },
  locale: string,
  t: ReturnType<typeof useT>,
): string {
  const date = new Date(`${event.day}T00:00:00`);
  const day = Number.isNaN(date.getTime())
    ? event.day
    : date.toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  return event.all_day
    ? `${day} · ${t("chat.card.cal.allDay")}`
    : `${day} · ${event.start_time} · ${t("chat.card.cal.minutes", { n: event.minutes })}`;
}

/** Only web links to a calendar are made clickable. */
function safeLink(link: string | null | undefined): string | null {
  return link && /^https:\/\//.test(link) ? link : null;
}

function EventLine({ event, locale, label }: { event: CalendarEventDraft; locale: string; label?: string }) {
  const t = useT();
  return (
    <div className="rounded-xl bg-surface-2/60 px-3 py-2">
      {label ? <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p> : null}
      <p className="font-medium">{event.summary}</p>
      <p className="text-xs text-muted">{whenText(event, locale, t)}</p>
      {event.description ? <p className="mt-1 whitespace-pre-wrap text-xs text-muted">{event.description}</p> : null}
    </div>
  );
}

function CalendarProposalCard({
  data,
  onDecide,
  busy,
}: {
  data: CalendarProposal;
  onDecide?: DecideFn;
  busy: boolean;
}) {
  const t = useT();
  const locale = useLocale();
  const [editing, setEditing] = useState(false);
  const [sending, setSending] = useState<"approve" | "reject" | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [draft, setDraft] = useState({
    summary: data.event.summary,
    description: data.event.description,
    day: data.event.day,
    start_time: data.event.start_time,
    minutes: String(data.event.minutes),
  });
  const pending = data.status === "pending";
  const Icon = data.action === "remove" ? CalendarX : data.action === "move" ? CalendarClock : CalendarPlus;
  const link = safeLink(data.result?.link);

  /** Only what the student actually changed is sent. */
  function edits(): CalendarEdits | undefined {
    const changed: CalendarEdits = {};
    if (draft.summary.trim() !== data.event.summary) changed.summary = draft.summary.trim();
    if (draft.description !== data.event.description) changed.description = draft.description;
    if (draft.day !== data.event.day) changed.day = draft.day;
    if (draft.start_time !== data.event.start_time) changed.start_time = draft.start_time;
    const minutes = Number(draft.minutes);
    if (Number.isFinite(minutes) && minutes !== data.event.minutes) changed.minutes = minutes;
    return Object.keys(changed).length > 0 ? changed : undefined;
  }

  async function answer(decision: "approve" | "reject") {
    if (!onDecide) return;
    setProblem(null);
    setSending(decision);
    try {
      await onDecide(data.run_id, decision, decision === "approve" ? edits() : undefined);
    } catch (caught) {
      setProblem(errorMessage(caught, t));
    } finally {
      setSending(null);
    }
  }

  const failure =
    data.error === "invalid_edit"
      ? t("chat.card.cal.invalid")
      : data.error === "gcal_reconnect"
        ? t("errors.gcal_reconnect")
        : data.error === "gcal_not_connected"
          ? t("errors.gcal_not_connected")
          : t("chat.card.cal.failed");

  return (
    <Shell icon={<Icon className={ICON} aria-hidden />} title={t(`chat.card.cal.title.${data.action}` as MessageKey)}>
      <div className="space-y-2">
        {data.action === "move" && data.before ? (
          <>
            <EventLine event={data.before} locale={locale} label={t("chat.card.cal.before")} />
            <EventLine event={data.event} locale={locale} label={t("chat.card.cal.after")} />
          </>
        ) : (
          <EventLine event={data.event} locale={locale} />
        )}
      </div>

      {pending && editing ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Field
            className="sm:col-span-2"
            label={t("chat.card.cal.f.title")}
            value={draft.summary}
            maxLength={200}
            onChange={(event) => setDraft({ ...draft, summary: event.target.value })}
          />
          <Field
            label={t("chat.card.cal.f.day")}
            type="date"
            value={draft.day}
            onChange={(event) => setDraft({ ...draft, day: event.target.value })}
          />
          <Field
            label={t("chat.card.cal.f.time")}
            type="time"
            value={draft.start_time}
            hint={t("chat.card.cal.f.timeHint")}
            onChange={(event) => setDraft({ ...draft, start_time: event.target.value })}
          />
          <Field
            label={t("chat.card.cal.f.length")}
            type="number"
            min={5}
            max={1440}
            value={draft.minutes}
            onChange={(event) => setDraft({ ...draft, minutes: event.target.value })}
          />
          <label className="sm:col-span-2">
            <span className="mb-1.5 block text-sm font-medium">{t("chat.card.cal.f.notes")}</span>
            <textarea
              value={draft.description}
              maxLength={2000}
              rows={2}
              onChange={(event) => setDraft({ ...draft, description: event.target.value })}
              className="w-full rounded-lg border border-border bg-surface-2/60 px-3 py-2 text-sm"
            />
          </label>
        </div>
      ) : null}

      {pending ? (
        <div className="mt-3">
          <p className="mb-2 text-xs text-muted">{t("chat.card.cal.ask")}</p>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void answer("approve")} loading={sending === "approve"} disabled={busy || sending !== null || !onDecide}>
              {t("chat.card.cal.approve")}
            </Button>
            {data.editable ? (
              <Button variant="secondary" onClick={() => setEditing(!editing)} disabled={busy || sending !== null}>
                {editing ? t("chat.card.cal.doneEditing") : t("chat.card.cal.edit")}
              </Button>
            ) : null}
            <Button variant="ghost" onClick={() => void answer("reject")} loading={sending === "reject"} disabled={busy || sending !== null || !onDecide}>
              {t("chat.card.cal.cancel")}
            </Button>
          </div>
        </div>
      ) : data.status === "approved" ? (
        <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="flex items-center gap-1.5 text-success">
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
            {t(`chat.card.cal.approved.${data.action}` as MessageKey)}
          </span>
          {link ? (
            <a href={link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
              {t("chat.card.cal.open")}
              <ExternalLink className="h-3 w-3" aria-hidden />
            </a>
          ) : null}
        </p>
      ) : data.status === "failed" ? (
        <p className="mt-3 flex items-start gap-1.5 text-xs text-danger">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {failure}
        </p>
      ) : (
        <p className="mt-3 text-xs text-muted">
          {data.status === "rejected" ? t("chat.card.cal.rejected") : t("chat.card.cal.expired")}
        </p>
      )}
      {problem ? <p className="mt-2 text-xs text-danger" role="alert">{problem}</p> : null}
    </Shell>
  );
}

function CalendarEventsCard({ data }: { data: { start: string; end: string; events: CalendarEventView[] } }) {
  const t = useT();
  const locale = useLocale();
  return (
    <Shell icon={<CalendarClock className={ICON} aria-hidden />} title={`${t("chat.card.cal.events.title")} · ${data.start} – ${data.end}`}>
      {data.events.length === 0 ? (
        <p className="text-xs text-muted">{t("chat.card.cal.events.empty")}</p>
      ) : (
        <ul className="space-y-1.5">
          {data.events.map((event, index) => {
            const link = safeLink(event.link);
            return (
              <li key={event.id ?? index} className="rounded-xl bg-surface-2/60 px-3 py-2">
                <p className="font-medium">
                  {link ? (
                    <a href={link} target="_blank" rel="noopener noreferrer" className="hover:underline">
                      {event.summary}
                    </a>
                  ) : (
                    event.summary
                  )}
                </p>
                <p className="text-xs text-muted">{whenText(event, locale, t)}</p>
              </li>
            );
          })}
        </ul>
      )}
    </Shell>
  );
}

function CalendarConnectCard({ data }: { data: { reason: "not_connected" | "reconnect" } }) {
  const t = useT();
  return (
    <Shell icon={<CalendarClock className={ICON} aria-hidden />} title={t("chat.card.cal.connect.title")}>
      <p className="text-xs text-muted">
        {data.reason === "reconnect" ? t("chat.card.cal.connect.reconnect") : t("chat.card.cal.connect.not_connected")}
      </p>
      <Link href="/calendar" className="mt-2 inline-block text-xs text-primary hover:underline">
        {t("chat.card.cal.connect.button")}
      </Link>
    </Shell>
  );
}
