"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { QuizDisplayBadge } from "@/components/quizzes/parts";
import { Alert, Button } from "@/components/ui";
import { useLocale, useT } from "@/i18n/client";
import { ApiError, api } from "@/lib/api";
import {
  beginAttempt,
  failureText,
  formatPercent,
  formatPoints,
  isWriting,
  quizError,
  typeLabelKey,
} from "@/lib/quiz";
import type { AttemptBrief, QuizDetail, QuizType } from "@/lib/types";

const POLL_MS = 3000;

export function QuizDetailView({ quizId }: { quizId: string }) {
  const t = useT();
  const locale = useLocale();
  const router = useRouter();
  const [quiz, setQuiz] = useState<QuizDetail | null>(null);
  const [attempts, setAttempts] = useState<AttemptBrief[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [starting, setStarting] = useState(false);
  const [archiving, setArchiving] = useState(false);

  const load = useCallback(async () => {
    try {
      const [loaded, past] = await Promise.all([
        api<QuizDetail>(`/quizzes/${quizId}`),
        api<AttemptBrief[]>(`/quizzes/${quizId}/attempts`),
      ]);
      setQuiz(loaded);
      setAttempts(past);
      setError(null);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 404) setMissing(true);
      else setError(quizError(caught, t));
    }
  }, [quizId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const busy = quiz !== null && isWriting(quiz.status);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [busy, load]);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      router.push(`/quizzes/attempt/${await beginAttempt(quizId)}`);
    } catch (caught) {
      setError(quizError(caught, t));
      setStarting(false);
    }
  }

  async function setArchived(archived: boolean) {
    setArchiving(true);
    setError(null);
    try {
      await api(`/quizzes/${quizId}`, { method: "PATCH", body: { archived } });
      await load();
    } catch (caught) {
      setError(quizError(caught, t));
    } finally {
      setArchiving(false);
    }
  }

  const back = (
    <Link href="/quizzes" className="mb-4 inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
      <ChevronLeft className="h-4 w-4" aria-hidden />
      {t("quiz.detail.back")}
    </Link>
  );

  if (missing) {
    return (
      <>
        {back}
        <Alert>{t("errors.not_found")}</Alert>
      </>
    );
  }
  if (!quiz) {
    return (
      <>
        {back}
        {error ? <Alert>{error}</Alert> : <p className="py-6 text-muted">{t("common.loading")}</p>}
      </>
    );
  }

  const typeCounts = quiz.questions.reduce<Partial<Record<QuizType, number>>>((counts, question) => {
    counts[question.qtype] = (counts[question.qtype] ?? 0) + 1;
    return counts;
  }, {});

  return (
    <>
      {back}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{quiz.title}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            <QuizDisplayBadge status={quiz.display_status} />
            <span>
              {quiz.source === "revision" ? t("quiz.list.revisionTag") : (quiz.subject_name ?? "")}
              {" · "}
              {t(`eval.lang.${quiz.language}`)}
              {quiz.config.basis === "general" ? ` · ${t("chat.card.quiz.general")}` : ""}
            </span>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {quiz.status === "ready" ? (
            <Button variant="secondary" loading={archiving} onClick={() => void setArchived(quiz.archived_at === null)}>
              {quiz.archived_at === null ? t("qzx.archive") : t("qzx.restore")}
            </Button>
          ) : null}
          {quiz.status === "ready" && quiz.archived_at === null ? (
            <Button loading={starting} onClick={() => void start()}>
              {quiz.open_attempt_id
                ? t("quiz.detail.resume")
                : attempts.length > 0
                  ? t("quiz.detail.retake")
                  : t("quiz.detail.start")}
            </Button>
          ) : null}
        </div>
      </div>

      {error ? (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      {quiz.archived_at !== null ? (
        <div className="mb-4">
          <Alert tone="info">{t("qzx.archivedNote")}</Alert>
        </div>
      ) : null}
      {isWriting(quiz.status) ? <Alert tone="info">{t("quiz.detail.writingLong")}</Alert> : null}
      {quiz.status === "failed" ? (
        <div className="space-y-2">
          <Alert>{failureText(quiz.error, t)}</Alert>
          <p className="text-sm text-muted">{t("quiz.detail.failedHint")}</p>
        </div>
      ) : null}

      {quiz.status === "ready" ? (
        <section className="rounded-card border border-border bg-surface p-5">
          <p className="text-sm">{t("quiz.list.questions", { count: quiz.question_count })}</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {(Object.entries(typeCounts) as [QuizType, number][]).map(([type, count]) => (
              <li key={type} className="rounded bg-bg px-3 py-1 text-xs text-muted">
                {t(typeLabelKey(type))} · {count}
              </li>
            ))}
          </ul>
          {quiz.rejected_count > 0 ? (
            <p className="mt-3 text-xs text-muted">{t("qzx.rejected", { count: quiz.rejected_count })}</p>
          ) : null}
          {quiz.questions.some((question) => question.qtype === "short") ? (
            <p className="mt-3 text-xs text-muted">{t("quiz.detail.shortHint")}</p>
          ) : null}
        </section>
      ) : null}

      {quiz.status === "ready" ? (
        <section className="mt-8" aria-labelledby="quiz-attempts">
          <h2 id="quiz-attempts" className="text-lg font-semibold">
            {t("quiz.detail.attempts")}
          </h2>
          {attempts.length === 0 ? (
            <p className="mt-3 text-sm text-muted">{t("quiz.detail.noAttempts")}</p>
          ) : (
            <ul className="mt-3 divide-y divide-border rounded-card border border-border bg-surface">
              {attempts.map((attempt) => (
                <li key={attempt.id}>
                  <Link
                    href={`/quizzes/attempt/${attempt.id}`}
                    className="flex items-center justify-between gap-3 px-4 py-3 text-sm hover:bg-bg"
                  >
                    <span className="text-muted">
                      {attempt.finished_at
                        ? new Date(attempt.finished_at).toLocaleString(locale, {
                            day: "numeric",
                            month: "short",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : t("quiz.detail.marking")}
                    </span>
                    <span className="font-medium tabular-nums">
                      {attempt.status === "grading"
                        ? t("quiz.detail.marking")
                        : attempt.total > 0
                          ? `${t("quiz.detail.score", {
                              points: formatPoints(attempt.points),
                              total: attempt.total,
                            })} · ${formatPercent(attempt.percent)}`
                          : "–"}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}
    </>
  );
}
