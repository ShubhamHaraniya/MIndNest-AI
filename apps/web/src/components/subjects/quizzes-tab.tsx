"use client";

import { ListChecks } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { Badge, type Tone } from "@/components/kit/badge";
import { ButtonLink } from "@/components/kit/button";
import { Panel } from "@/components/kit/panel";
import { EmptyState, ErrorState } from "@/components/kit/states";
import { Skeleton } from "@/components/kit/skeleton";
import { Table, TBody, THead, Td, Th, Tr } from "@/components/kit/table";
import { useLocale, useT } from "@/i18n/client";
import type { MessageKey } from "@/i18n/translate";
import { percent, relativeTime } from "@/lib/format";

import type { CourseFigures, QuizBrief } from "./model";
import type { Resource } from "./use-resource";

const STATUS_TONE: Record<string, Tone> = { ready: "success", failed: "danger", queued: "info", generating: "info" };
const STATUS_KEYS: Record<string, MessageKey> = {
  ready: "quiz.status.ready",
  failed: "quiz.status.failed",
  queued: "quiz.status.queued",
  generating: "quiz.status.generating",
};

/** The quizzes written for this course, with the attempts and last score for each. Making a new
 *  quiz and taking it happen on the Quiz & Practice pages; this is the course's own history. */
export function QuizzesTab({
  quizzes,
  course,
  subjectId,
  readyDocuments,
}: {
  quizzes: Resource<QuizBrief[]>;
  course: CourseFigures | null;
  subjectId: string;
  readyDocuments: number;
}) {
  const t = useT();
  const locale = useLocale();
  const mine = useMemo(
    () => (quizzes.data ?? []).filter((quiz) => quiz.subject_id === subjectId && quiz.source === "subject"),
    [quizzes.data, subjectId],
  );
  const newQuiz = (
    <ButtonLink
      href={`/quizzes?subject=${subjectId}`}
      size="sm"
      aria-disabled={readyDocuments === 0}
      title={readyDocuments === 0 ? t("sj.quizzes.needDocuments") : undefined}
      className={readyDocuments === 0 ? "pointer-events-none opacity-50" : undefined}
      tabIndex={readyDocuments === 0 ? -1 : undefined}
    >
      <ListChecks className="h-3.5 w-3.5" aria-hidden />
      {t("sj.quizzes.new")}
    </ButtonLink>
  );

  if (quizzes.error && !quizzes.data) return <ErrorState compact description={quizzes.error} onRetry={quizzes.reload} />;

  return (
    <Panel
      id="course-quizzes"
      title={t("sj.tab.quizzes")}
      description={
        course && course.quiz_attempts > 0
          ? t("sj.quizzes.summary", { attempts: course.quiz_attempts, average: percent(course.quiz_average) })
          : undefined
      }
      action={newQuiz}
    >
      {quizzes.loading ? (
        <div className="space-y-3 p-3.5" aria-hidden>
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-4 w-full" />
          ))}
        </div>
      ) : mine.length === 0 ? (
        <div className="px-4 py-8">
          <EmptyState compact icon={ListChecks} title={t("sj.quizzes.emptyTitle")} description={t("sj.quizzes.emptyBody")}>
            {readyDocuments > 0 ? <ButtonLink href={`/quizzes?subject=${subjectId}`}>{t("sj.quizzes.new")}</ButtonLink> : null}
          </EmptyState>
        </div>
      ) : (
        <Table caption={t("sj.tab.quizzes")}>
          <THead>
            <tr>
              <Th className="w-full">{t("sj.col.quiz")}</Th>
              <Th>{t("sj.col.status")}</Th>
              <Th align="right" className="hidden sm:table-cell">
                {t("sj.col.questions")}
              </Th>
              <Th align="right">{t("sj.col.attempts")}</Th>
              <Th>{t("sj.col.lastScore")}</Th>
              <Th className="hidden md:table-cell">{t("sj.col.created")}</Th>
              <Th>
                <span className="sr-only">{t("sj.col.actions")}</span>
              </Th>
            </tr>
          </THead>
          <TBody>
            {mine.map((quiz) => {
              const last = quiz.last_attempt;
              return (
                <Tr key={quiz.id}>
                  <Td className="max-w-0">
                    <Link href={`/quizzes/${quiz.id}`} className="block truncate font-medium hover:text-brand" title={quiz.title}>
                      {quiz.title}
                    </Link>
                  </Td>
                  <Td className="whitespace-nowrap">
                    <Badge tone={STATUS_TONE[quiz.status] ?? "neutral"}>{t(STATUS_KEYS[quiz.status] ?? "quiz.status.queued")}</Badge>
                  </Td>
                  <Td align="right" className="tabular hidden text-muted sm:table-cell">
                    {quiz.question_count}
                  </Td>
                  <Td align="right" className="tabular">
                    {quiz.attempts}
                  </Td>
                  <Td className="whitespace-nowrap">
                    {last && last.percent !== null ? (
                      <span className="tabular">
                        <span className="font-medium">{percent(last.percent)}</span>
                        <span className="ml-1.5 text-xs text-muted">{t("quiz.detail.score", { points: last.points, total: last.total })}</span>
                      </span>
                    ) : last ? (
                      <span className="text-xs text-muted">{t("quiz.detail.marking")}</span>
                    ) : (
                      <span className="text-faint">—</span>
                    )}
                  </Td>
                  <Td className="hidden whitespace-nowrap text-muted md:table-cell">{relativeTime(quiz.created_at, locale)}</Td>
                  <Td align="right" className="whitespace-nowrap">
                    {last ? (
                      <Link href={`/quizzes/attempt/${last.id}`} className="text-xs font-medium text-brand hover:underline">
                        {t("sj.quizzes.review")}
                      </Link>
                    ) : null}
                    {quiz.status === "ready" ? (
                      <Link href={`/quizzes/${quiz.id}`} className="ml-3 text-xs font-medium text-brand hover:underline">
                        {last ? t("quiz.detail.retake") : t("quiz.detail.start")}
                      </Link>
                    ) : null}
                  </Td>
                </Tr>
              );
            })}
          </TBody>
        </Table>
      )}
    </Panel>
  );
}
