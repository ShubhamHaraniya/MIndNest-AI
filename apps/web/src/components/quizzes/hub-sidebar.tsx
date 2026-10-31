"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/kit/button";
import { Select } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { Skeleton } from "@/components/kit/skeleton";
import { useToast } from "@/components/kit/toast";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { formatDay } from "@/lib/format";
import { beginAttempt, formatPercent, quizError } from "@/lib/quiz";
import type { Quiz, QuizProgress, Subject } from "@/lib/types";

/** The right-hand column of the hub: revision cards that are due, results by course and the
 *  most recent attempts. All of it is the student's own data from `/progress`. */
export function HubSidebar({
  progress,
  course,
  subjects,
  onStarted,
}: {
  progress: QuizProgress | null;
  course: string;
  subjects: Subject[];
  onStarted: (attemptId: string) => void;
}) {
  if (!progress) {
    return (
      <div className="space-y-4" aria-hidden>
        <Skeleton className="h-44 w-full" />
        <Skeleton className="h-36 w-full" />
      </div>
    );
  }
  return (
    <div className="min-w-0 space-y-4">
      <RevisionPanel progress={progress} course={course} subjects={subjects} onStarted={onStarted} />
      <CoursePanel progress={progress} />
      <RecentPanel progress={progress} />
    </div>
  );
}

function RevisionPanel({
  progress,
  course,
  subjects,
  onStarted,
}: {
  progress: QuizProgress;
  course: string;
  subjects: Subject[];
  onStarted: (attemptId: string) => void;
}) {
  const t = useT();
  const locale = useLocale();
  const toast = useToast();
  const [chosen, setChosen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const revision = progress.revision;
  const withDue = revision.due_by_subject.filter((row) => row.subject_id);
  // The course chosen in the table's filter wins until the student picks one here.
  const subjectId = chosen ?? (course && withDue.some((row) => row.subject_id === course) ? course : "");
  const due = subjectId ? (withDue.find((row) => row.subject_id === subjectId)?.due ?? 0) : revision.due;
  const known = new Set(subjects.map((subject) => subject.id));
  const boxes = ["1", "2", "3", "4", "5"];
  const biggest = Math.max(1, ...boxes.map((box) => revision.boxes[box] ?? 0));
  const nextDue = revision.next_due_at ? formatDay(revision.next_due_at.slice(0, 10), locale, { day: "numeric", month: "short" }) : null;

  async function start() {
    setBusy(true);
    try {
      const quiz = await api<Quiz>("/revision/start", {
        method: "POST",
        body: { count: 10, subject_id: subjectId || null },
      });
      onStarted(await beginAttempt(quiz.id));
    } catch (caught) {
      toast.error(quizError(caught, t));
      setBusy(false);
    }
  }

  return (
    <Panel id="revision" title={t("quiz.revision.title")} description={t("qz.hub.revisionHint")}>
      <div className="space-y-3 px-3.5 py-3">
        <p className="text-[13px]">
          {revision.cards === 0
            ? t("quiz.revision.empty")
            : revision.due > 0
              ? t("quiz.revision.due", { count: revision.due })
              : t("quiz.revision.none")}
          {revision.due === 0 && nextDue ? <span className="text-muted"> {t("quiz.revision.next", { date: nextDue })}</span> : null}
        </p>
        {revision.due > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            {withDue.length > 1 ? (
              <Select
                aria-label={t("quiz.create.subject")}
                value={subjectId}
                onChange={(event) => setChosen(event.target.value)}
                className="h-8 max-w-[11rem] text-[13px]"
              >
                <option value="">{t("quiz.revision.allSubjects")}</option>
                {withDue
                  .filter((row) => row.subject_id && known.has(row.subject_id))
                  .map((row) => (
                    <option key={row.subject_id} value={row.subject_id ?? ""}>
                      {row.name} ({row.due})
                    </option>
                  ))}
              </Select>
            ) : null}
            <Button size="sm" loading={busy} disabled={due === 0} onClick={() => void start()}>
              {t("quiz.revision.start")}
              <span className="tabular opacity-80">· {Math.min(due, 10)}</span>
            </Button>
          </div>
        ) : null}
      </div>
      {revision.cards > 0 ? (
        <div className="border-t border-border px-3.5 py-2.5">
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">
            {t("qz.hub.boxes", { count: revision.cards })}
          </p>
          <ul className="space-y-1" aria-label={t("quiz.revision.boxesHint")}>
            {boxes.map((box) => (
              <li key={box} className="flex items-center gap-2 text-xs">
                <span className="w-12 shrink-0 text-muted">{t("quiz.revision.box", { n: box })}</span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3" aria-hidden>
                  <div className="h-full rounded-full bg-gradient-to-r from-primary to-accent" style={{ width: `${((revision.boxes[box] ?? 0) / biggest) * 100}%` }} />
                </div>
                <span className="tabular w-6 shrink-0 text-right">{revision.boxes[box] ?? 0}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Panel>
  );
}

function CoursePanel({ progress }: { progress: QuizProgress }) {
  const t = useT();
  return (
    <Panel
      id="by-course"
      title={t("quiz.progress.bySubject")}
      description={progress.attempts > 0 ? t("qz.hub.overall", { count: progress.attempts, average: formatPercent(progress.average) }) : undefined}
    >
      {progress.subjects.length === 0 ? (
        <p className="px-3.5 py-4 text-sm text-muted">{t("quiz.progress.none")}</p>
      ) : (
        <ul className="divide-y divide-border">
          {progress.subjects.map((row) => (
            <li key={row.subject_id ?? "none"} className="px-3.5 py-2">
              <div className="flex items-baseline justify-between gap-3">
                <p className="truncate text-[13px] font-medium">{row.name ?? t("quiz.progress.noSubject")}</p>
                <span className="tabular shrink-0 text-[13px] font-semibold">{formatPercent(row.average)}</span>
              </div>
              <div className="mt-1 flex items-center gap-3">
                <div
                  role="img"
                  aria-label={`${row.name ?? t("quiz.progress.noSubject")}: ${formatPercent(row.average)}`}
                  className="h-1 flex-1 bg-surface-3"
                >
                  <div className="h-full bg-primary" style={{ width: `${Math.round((row.average ?? 0) * 100)}%` }} />
                </div>
                <span className="tabular text-xs text-muted">{t("quiz.list.attempts", { count: row.attempts })}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function RecentPanel({ progress }: { progress: QuizProgress }) {
  const t = useT();
  const locale = useLocale();
  if (progress.recent.length === 0) return null;
  return (
    <Panel id="recent" title={t("quiz.progress.recent")}>
      <ul className="divide-y divide-border">
        {progress.recent.slice(0, 6).map((row) => (
          <li key={row.attempt_id}>
            <Link href={`/quizzes/attempt/${row.attempt_id}`} className="flex items-baseline justify-between gap-3 px-3.5 py-2 hover:bg-surface-2">
              <span className="min-w-0 truncate text-[13px]">{row.title}</span>
              <span className="tabular shrink-0 text-xs text-muted">
                <span className="text-[13px] font-medium text-ink">{formatPercent(row.percent)}</span>
                {row.finished_at ? ` · ${formatDay(row.finished_at.slice(0, 10), locale, { day: "numeric", month: "short" })}` : ""}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
