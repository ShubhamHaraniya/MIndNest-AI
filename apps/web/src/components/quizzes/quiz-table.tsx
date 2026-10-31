"use client";

import { Archive, ArchiveRestore, Loader2, Play, RotateCcw, Trash2 } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/kit/button";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/kit/table";
import { QuizDisplayBadge } from "@/components/quizzes/parts";
import { useLocale, useT } from "@/i18n/client";
import { relativeTime } from "@/lib/format";
import { failureText, formatPercent, isWriting } from "@/lib/quiz";
import type { Quiz } from "@/lib/types";

/** The student's quizzes as a dense table: what it is, where it stands, how they did, and the one
 *  next action (resume, start, or write it again). */
export function QuizTable({
  quizzes,
  busyId,
  onStart,
  onRetry,
  onDelete,
  onArchive,
  onRestore,
}: {
  quizzes: Quiz[];
  busyId: string | null;
  onStart: (quiz: Quiz) => void;
  onRetry: (quiz: Quiz) => void;
  onDelete: (quiz: Quiz) => void;
  onArchive: (quiz: Quiz) => void;
  onRestore: (quiz: Quiz) => void;
}) {
  const t = useT();
  const locale = useLocale();

  return (
    <Table caption={t("quiz.list.title")}>
      <THead>
        <tr>
          <Th>{t("qz.col.quiz")}</Th>
          <Th className="hidden md:table-cell">{t("qz.col.course")}</Th>
          <Th align="right" className="hidden sm:table-cell">
            {t("qz.col.questions")}
          </Th>
          <Th>{t("qz.col.status")}</Th>
          <Th align="right" className="hidden md:table-cell">
            {t("qz.col.attempts")}
          </Th>
          <Th align="right" className="hidden lg:table-cell">
            {t("qz.col.best")}
          </Th>
          <Th align="right" className="hidden lg:table-cell">
            {t("qz.col.last")}
          </Th>
          <Th className="hidden xl:table-cell">{t("qz.col.created")}</Th>
          <Th>
            <span className="sr-only">{t("qz.col.actions")}</span>
          </Th>
        </tr>
      </THead>
      <TBody>
        {quizzes.map((quiz) => {
          const last = quiz.last_attempt;
          const writing = isWriting(quiz.status);
          const busy = busyId === quiz.id;
          const course = quiz.source === "revision" && !quiz.subject_name ? t("quiz.list.revisionTag") : (quiz.subject_name ?? "–");
          const tags = [
            quiz.source === "revision" ? t("quiz.list.revisionTag") : null,
            quiz.config.basis === "general" ? t("chat.card.quiz.general") : null,
            quiz.config.focus ? String(quiz.config.focus) : null,
            quiz.time_limit_minutes ? t("qz.min", { n: quiz.time_limit_minutes }) : null,
          ].filter(Boolean);
          return (
            <Tr key={quiz.id}>
              <Td className="max-w-0 min-w-[10rem] sm:min-w-[14rem]">
                <Link href={`/quizzes/${quiz.id}`} className="block min-w-0 hover:text-brand">
                  <span className="block truncate font-medium" title={quiz.title}>
                    {quiz.title}
                  </span>
                  <span className="block truncate text-xs text-muted">
                    <span className="md:hidden">{course}</span>
                    <span className="sm:hidden">
                      {" · "}
                      {writing ? t("quiz.detail.writing") : t("quiz.list.questions", { count: quiz.question_count })}
                    </span>
                    {tags.length > 0 ? <span className="hidden md:inline">{tags.join(" · ")}</span> : null}
                    {last && last.percent !== null ? (
                      <span className="lg:hidden">
                        {" · "}
                        {t("quiz.list.lastScore", { percent: formatPercent(last.percent) })}
                      </span>
                    ) : null}
                  </span>
                </Link>
                {quiz.status === "failed" ? (
                  <span className="mt-0.5 block text-xs text-danger">{failureText(quiz.error, t)}</span>
                ) : null}
              </Td>
              <Td className="hidden max-w-[11rem] truncate text-muted md:table-cell" title={course}>
                {course}
              </Td>
              <Td align="right" className="tabular hidden text-muted sm:table-cell">
                {writing || quiz.status === "failed" ? "–" : quiz.question_count}
              </Td>
              <Td>
                <QuizDisplayBadge status={quiz.display_status} />
              </Td>
              <Td align="right" className="tabular hidden text-muted md:table-cell">
                {quiz.attempts}
              </Td>
              <Td align="right" className="tabular hidden lg:table-cell">
                {formatPercent(quiz.best_percent)}
              </Td>
              <Td align="right" className="tabular hidden lg:table-cell">
                {last ? (
                  <Link href={`/quizzes/attempt/${last.id}`} className="hover:text-brand hover:underline">
                    {formatPercent(last.percent)}
                  </Link>
                ) : (
                  "–"
                )}
              </Td>
              <Td className="hidden whitespace-nowrap text-xs text-muted xl:table-cell">{relativeTime(quiz.created_at, locale)}</Td>
              <Td align="right" className="whitespace-nowrap">
                <span className="inline-flex items-center justify-end gap-1">
                  {quiz.display_status === "archived" ? (
                    <Button size="sm" variant="secondary" loading={busy} onClick={() => onRestore(quiz)}>
                      <ArchiveRestore className="h-3 w-3" aria-hidden />
                      {t("qzx.restore")}
                    </Button>
                  ) : quiz.status === "ready" ? (
                    <Button size="sm" variant={quiz.open_attempt_id ? "primary" : "secondary"} loading={busy} onClick={() => onStart(quiz)}>
                      <Play className="h-3 w-3" aria-hidden />
                      {quiz.open_attempt_id ? t("qz.action.resume") : quiz.attempts > 0 ? t("qz.action.retake") : t("qz.action.start")}
                    </Button>
                  ) : quiz.status === "failed" ? (
                    <Button size="sm" variant="secondary" loading={busy} onClick={() => onRetry(quiz)}>
                      <RotateCcw className="h-3 w-3" aria-hidden />
                      {t("common.retry")}
                    </Button>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2 text-xs text-muted">
                      <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                      {t("quiz.detail.writing")}
                    </span>
                  )}
                  {quiz.status === "ready" && quiz.display_status !== "archived" ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="px-1.5"
                      aria-label={`${t("qzx.archive")}: ${quiz.title}`}
                      title={t("qzx.archive")}
                      onClick={() => onArchive(quiz)}
                    >
                      <Archive className="h-3.5 w-3.5" aria-hidden />
                    </Button>
                  ) : null}
                  <Button
                    size="sm"
                    variant="ghost"
                    className="px-1.5"
                    aria-label={`${t("common.delete")}: ${quiz.title}`}
                    title={t("common.delete")}
                    onClick={() => onDelete(quiz)}
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden />
                  </Button>
                </span>
              </Td>
            </Tr>
          );
        })}
      </TBody>
    </Table>
  );
}
