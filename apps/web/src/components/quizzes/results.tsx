"use client";

import clsx from "clsx";
import { CheckCircle2, CircleDashed, ExternalLink, MinusCircle, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { Segmented } from "@/components/kit/controls";
import { Facts, Panel } from "@/components/kit/panel";
import { Meter } from "@/components/dashboard/meter";
import { AnimatedRing } from "@/components/motion/ring";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/kit/table";
import { useToast } from "@/components/kit/toast";
import { INLINE_MD, QuizMarkdown } from "@/components/quizzes/parts";
import { Alert } from "@/components/ui";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import {
  WEAK_BELOW,
  beginAttempt,
  formatPercent,
  formatPoints,
  formatTaken,
  optionLetter,
  pointsDelta,
  quizError,
  typeLabelKey,
  verdictOf,
  type Analysis,
  type TopicStat,
  type Verdict,
} from "@/lib/quiz";
import { bcp47 } from "@/lib/format";
import type { Attempt, Quiz, QuizResult } from "@/lib/types";

const VERDICT_ICON: Record<Verdict, typeof CheckCircle2> = {
  correct: CheckCircle2,
  partial: MinusCircle,
  wrong: XCircle,
  pending: CircleDashed,
  unmarked: CircleDashed,
};
const VERDICT_COLOR: Record<Verdict, string> = {
  correct: "text-success",
  partial: "text-warning",
  wrong: "text-danger",
  pending: "text-faint",
  unmarked: "text-faint",
};

/** The analysed result of a finished attempt: score, topics, what to revise, every question with
 *  its explanation, and how this attempt compares with the earlier ones. */
export function Results({ attempt }: { attempt: Attempt }) {
  const t = useT();
  const locale = useLocale();
  const router = useRouter();
  const toast = useToast();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "missed">("all");
  const [busy, setBusy] = useState<"retake" | "practise" | null>(null);
  const grading = attempt.status === "grading";

  useEffect(() => {
    if (attempt.status === "in_progress") return;
    api<Analysis>(`/attempts/${attempt.id}/analysis`)
      .then(setAnalysis)
      .catch((caught: unknown) => setError(quizError(caught, t)));
  }, [attempt.id, attempt.status, attempt.finished_at, t]);

  const insight = useMemo(() => new Map((analysis?.questions ?? []).map((q) => [q.question_id, q])), [analysis]);
  const rows = attempt.results.filter((result) => {
    if (filter === "all") return true;
    const score = result.score;
    return score !== null && score < 0.99;
  });
  const previous = analysis?.history.filter((point) => point.attempt_id !== attempt.id && point.percent !== null && point.status === "completed").at(-1);
  const delta = analysis && previous ? pointsDelta(analysis.percent, previous.percent) : null;
  const weak = (analysis?.topics ?? []).filter((topic) => topic.accuracy !== null && topic.accuracy < WEAK_BELOW).sort((a, b) => (a.accuracy ?? 1) - (b.accuracy ?? 1));
  const missedCount = analysis?.missed ?? 0;

  async function practise() {
    setBusy("practise");
    try {
      const quiz = await api<Quiz>(`/attempts/${attempt.id}/practise-missed`, { method: "POST" });
      toast.success(t("qr.recs.practiseDone"));
      router.push(`/quizzes/${quiz.id}`);
    } catch (caught) {
      setError(quizError(caught, t));
      setBusy(null);
    }
  }

  async function retake() {
    setBusy("retake");
    try {
      router.push(`/quizzes/attempt/${await beginAttempt(attempt.quiz_id)}`);
    } catch (caught) {
      setError(quizError(caught, t));
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-2xl leading-tight">{attempt.quiz_title}</h1>
          <p className="mt-0.5 text-[13px] text-muted">{t("quiz.result.title")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {missedCount > 0 ? (
            <Button variant="secondary" size="sm" loading={busy === "practise"} onClick={() => void practise()}>
              {t("qr.recs.practise", { count: missedCount })}
            </Button>
          ) : null}
          <Button size="sm" loading={busy === "retake"} onClick={() => void retake()}>
            {t("qr.retake")}
          </Button>
        </div>
      </header>

      {error ? <Alert>{error}</Alert> : null}
      {grading ? <Alert tone="info">{t("qr.grading")}</Alert> : null}
      {attempt.unscored > 0 && !grading ? <Alert tone="info">{t("quiz.result.unscored", { count: attempt.unscored })}</Alert> : null}

      <section className="glass sheen rounded-3xl p-5 sm:p-7" aria-label={t("quiz.result.title")}>
        <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
          <div className="flex items-center gap-4">
            <AnimatedRing
              value={grading ? 0 : (attempt.percent ?? 0)}
              size={120}
              stroke={10}
              label={t("qr.score")}
              tone={grading || attempt.percent === null ? "primary" : attempt.percent >= 0.8 ? "success" : attempt.percent >= 0.5 ? "primary" : "danger"}
            >
              <span className="tabular font-display text-3xl leading-none">{grading ? "–" : formatPercent(attempt.percent)}</span>
            </AnimatedRing>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-faint rtl:tracking-normal">{t("qr.score")}</p>
              <p className="tabular mt-1 text-lg font-semibold leading-none">
                {t("qr.of", { points: formatPoints(attempt.points), total: formatPoints(attempt.total) })}
              </p>
            </div>
          </div>
          <Facts
            className="flex-1 grid-cols-2 sm:grid-cols-4"
            items={[
              {
                label: t("qr.time"),
                value: analysis ? `${formatTaken(analysis.duration_seconds, t)}${analysis.limit_seconds ? ` / ${formatTaken(analysis.limit_seconds, t)}` : ""}` : "–",
              },
              { label: t("qr.vsLast"), value: delta ? `${delta} ${locale === "en" ? "pts" : "%"}` : t("qr.firstAttempt") },
              { label: t("qr.courseAvg"), value: formatPercent(analysis?.course?.average) },
              { label: t("quiz.progress.attempts"), value: analysis ? String(analysis.history.length) : "–" },
            ]}
          />
        </div>
      </section>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_23rem]">
        <Panel
          id="review"
          title={t("qr.review.title")}
          action={
            <Segmented<"all" | "missed">
              label={t("qr.review.filter")}
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: t("qr.review.all") },
                { value: "missed", label: t("qr.review.missed") },
              ]}
            />
          }
        >
          {rows.length === 0 ? (
            <p className="px-3.5 py-4 text-[13px] text-muted">{t("qr.review.none")}</p>
          ) : (
            <ol className="divide-y divide-border">
              {rows.map((result) => (
                <ReviewRow key={result.question_id} result={result} waiting={grading} topic={insight.get(result.question_id)?.topic ?? null} />
              ))}
            </ol>
          )}
        </Panel>

        <div className="space-y-4">
          <Panel id="topics" title={t("qr.topics.title")}>
            {analysis && analysis.topics.length > 0 ? (
              <Table caption={t("qr.topics.title")}>
                <THead>
                  <tr>
                    <Th>{t("qr.topics.topic")}</Th>
                    <Th align="right">{t("qr.topics.accuracy")}</Th>
                    <Th align="right">{t("qr.topics.earlier")}</Th>
                  </tr>
                </THead>
                <TBody>
                  {analysis.topics.map((topic, index) => (
                    <TopicRow key={`${topic.material_id ?? topic.topic ?? "general"}-${index}`} topic={topic} />
                  ))}
                </TBody>
              </Table>
            ) : (
              <p className="px-3.5 py-4 text-[13px] text-muted">{analysis ? t("qr.topics.empty") : t("common.loading")}</p>
            )}
          </Panel>

          <Panel id="revise" title={t("qr.recs.title")} description={analysis?.revision.due_now ? t("qr.recs.due", { count: analysis.revision.due_now }) : undefined}>
            {analysis === null ? (
              <p className="px-3.5 py-4 text-[13px] text-muted">{t("common.loading")}</p>
            ) : weak.length === 0 && missedCount === 0 ? (
              <p className="px-3.5 py-4 text-[13px] text-muted">{t("qr.recs.none")}</p>
            ) : (
              <>
                <ul className="divide-y divide-border">
                  {weak.map((topic, index) => (
                    <li key={`${topic.material_id ?? topic.topic}-${index}`} className="px-3.5 py-2.5 text-[13px]">
                      <p className="font-medium">{topic.topic ?? topic.module ?? t("qr.topics.general")}</p>
                      <p className="tabular text-xs text-muted">{t("qr.recs.weak", { accuracy: formatPercent(topic.accuracy), missed: topic.missed })}</p>
                      {topic.material_id ? (
                        <a
                          href={`/api/v1/materials/${topic.material_id}/download?inline=true`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline"
                        >
                          {t("qr.recs.open")}
                          <ExternalLink className="h-3 w-3" aria-hidden />
                        </a>
                      ) : null}
                    </li>
                  ))}
                </ul>
                <p className="border-t border-border px-3.5 py-2 text-xs text-muted">{t("qr.recs.scheduled")}</p>
              </>
            )}
          </Panel>

          <Panel id="history" title={t("qr.history.title")}>
            {analysis === null ? (
              <p className="px-3.5 py-4 text-[13px] text-muted">{t("common.loading")}</p>
            ) : analysis.history.length <= 1 ? (
              <p className="px-3.5 py-4 text-[13px] text-muted">{t("qr.history.alone")}</p>
            ) : (
              <ul className="divide-y divide-border">
                {analysis.history.map((point) => {
                  const current = point.attempt_id === attempt.id;
                  const date = new Intl.DateTimeFormat(bcp47(locale), { day: "numeric", month: "short" }).format(new Date(point.finished_at ?? point.started_at));
                  return (
                    <li key={point.attempt_id} className={clsx("px-3.5 py-2 text-[13px]", current && "bg-primary-soft")}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="tabular text-muted">{date}</span>
                        {current ? <Badge tone="brand">{t("qr.history.this")}</Badge> : null}
                        <span className="tabular font-medium">{formatPercent(point.percent)}</span>
                      </div>
                      <Meter value={point.percent ?? 0} label={`${date} ${formatPercent(point.percent)}`} className="mt-1.5" />
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function TopicRow({ topic }: { topic: TopicStat }) {
  const t = useT();
  const accuracy = topic.accuracy;
  const tone = accuracy === null ? "primary" : accuracy >= WEAK_BELOW ? "primary" : accuracy >= 0.5 ? "warning" : "danger";
  const label = topic.topic ?? topic.module ?? t("qr.topics.general");
  return (
    <Tr>
      <Td className="max-w-[10rem]">
        <p className="truncate font-medium" title={label}>
          {label}
        </p>
        <Meter value={accuracy ?? 0} tone={tone} label={`${label} ${formatPercent(accuracy)}`} className="mt-1.5" />
      </Td>
      <Td align="right" className="tabular">
        {formatPercent(accuracy)}
      </Td>
      <Td align="right" className="tabular text-muted">
        {formatPercent(topic.earlier_accuracy)}
      </Td>
    </Tr>
  );
}

function ReviewRow({ result, waiting, topic }: { result: QuizResult; waiting: boolean; topic: string | null }) {
  const t = useT();
  const verdict = verdictOf(result.score, waiting && result.qtype === "short");
  const Icon = VERDICT_ICON[verdict];
  const choice = (value: string) => {
    if (result.qtype !== "mcq" || !result.options) return value;
    const index = result.options.findIndex((option) => option === value);
    return index >= 0 ? `${optionLetter(index)}. ${value}` : value;
  };
  return (
    <li className="relative px-4 py-3.5 pl-5">
      <span
        aria-hidden
        className={clsx(
          "absolute inset-y-2 left-0 w-1 rounded-full",
          verdict === "correct" ? "bg-success" : verdict === "partial" ? "bg-warning" : verdict === "wrong" ? "bg-danger" : "bg-border-strong",
        )}
        style={verdict === "correct" || verdict === "wrong" ? { boxShadow: `0 0 10px ${verdict === "correct" ? "var(--success)" : "var(--danger)"}` } : undefined}
      />
      <div className="flex items-start gap-2.5">
        <Icon className={clsx("mt-0.5 h-4 w-4 shrink-0", VERDICT_COLOR[verdict])} aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
            <span className="font-semibold text-ink">{t("qr.review.question", { n: result.position + 1 })}</span>
            <span>{t(typeLabelKey(result.qtype))}</span>
            {topic ? <Badge>{topic}</Badge> : null}
            <span className={clsx("font-medium", VERDICT_COLOR[verdict])}>{t(`quiz.result.${verdict}`)}</span>
          </p>
          <QuizMarkdown text={result.prompt} className={clsx("mt-1", INLINE_MD)} />
          <dl className="mt-2 space-y-1.5 text-[13px]">
            <div>
              <dt className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{t("quiz.result.yourAnswer")}</dt>
              <dd className={clsx(verdict === "wrong" && "text-danger")}>{result.response.trim() ? choice(result.response) : t("quiz.result.noAnswer")}</dd>
            </div>
            {verdict !== "correct" ? (
              <div>
                <dt className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{t("quiz.result.correctAnswer")}</dt>
                <dd>{choice(result.answer)}</dd>
              </div>
            ) : null}
            {result.feedback ? (
              <div>
                <dt className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{t("quiz.result.feedback")}</dt>
                <dd className="text-muted">{result.feedback}</dd>
              </div>
            ) : null}
            {result.explanation ? (
              <div>
                <dt className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{t("quiz.result.explanation")}</dt>
                <dd>
                  <QuizMarkdown text={result.explanation} className={clsx("text-muted", INLINE_MD)} />
                </dd>
              </div>
            ) : null}
            {result.source?.filename ? (
              <p className="border-l-2 border-border-strong pl-2 text-xs text-muted">
                {result.source.page ? t("quiz.result.sourcePage", { file: result.source.filename, page: result.source.page }) : result.source.filename}
              </p>
            ) : null}
          </dl>
        </div>
      </div>
    </li>
  );
}
