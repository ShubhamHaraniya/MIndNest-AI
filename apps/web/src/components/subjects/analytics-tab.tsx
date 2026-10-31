"use client";

import { BarChart3, TrendingDown, TrendingUp } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/kit/badge";
import { Segmented } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { ProgressBar } from "@/components/kit/progress";
import { ErrorState } from "@/components/kit/states";
import { Skeleton } from "@/components/kit/skeleton";
import { Table, TBody, THead, Td, Th, Tr } from "@/components/kit/table";
import { useLocale, useT } from "@/i18n/client";
import { bcp47, formatDay, percent } from "@/lib/format";

import { microLabel } from "./bits";
import { ScoreChart, WeeklyChart } from "./charts";
import type { CourseAnalytics, CourseFigures, CourseProgress } from "./model";
import { ProgressTab } from "./progress-tab";
import type { Resource } from "./use-resource";

type View = "chart" | "table";

/** How the course is going: quiz scores over time, practice by week, accuracy by question type,
 *  how much has been read and tried, and how the progress figure is made. Below it, the accuracy
 *  of each module and file. Every figure comes from what the student has actually done; where
 *  nothing has been measured the page says so instead of showing zero. */
export function AnalyticsTab({
  analytics,
  figures,
  progress,
  subjectId,
  onOpenDoc,
  onOpenModule,
  onAsk,
}: {
  analytics: Resource<CourseAnalytics>;
  figures: CourseFigures | null;
  progress: Resource<CourseProgress>;
  subjectId: string;
  onOpenDoc: (id: string) => void;
  onOpenModule: (module: string) => void;
  onAsk: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const [view, setView] = useState<View>("chart");
  const data = analytics.data;

  if (analytics.error && !data) return <ErrorState compact description={analytics.error} onRetry={analytics.reload} />;
  if (analytics.loading || !data) {
    return (
      <div className="space-y-4" aria-hidden>
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  const date = (iso: string) => new Intl.DateTimeFormat(bcp47(locale), { day: "numeric", month: "short", year: "numeric" }).format(new Date(iso));
  const facts = [
    {
      label: t("sj.an.progress"),
      value: data.progress === null ? t("sj.an.notMeasured") : percent(data.progress),
    },
    { label: t("sj.an.average"), value: percent(figures?.quiz_average ?? null) },
    {
      label: t("sj.an.coverage"),
      value:
        data.coverage.documents_ready === 0
          ? "—"
          : t("sj.an.coverageValue", { practised: data.coverage.documents_practised, ready: data.coverage.documents_ready }),
    },
    { label: t("sj.an.cardsDue"), value: String(data.revision.due) },
    { label: t("sj.an.overdue"), value: String(data.assignments.overdue), warn: data.assignments.overdue > 0 },
  ];
  const noAttempts = data.attempts.length === 0;
  const practised = data.weeks.some((w) => w.answers > 0);

  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 divide-x divide-y divide-border rounded-card border border-border bg-surface sm:grid-cols-3 sm:divide-y-0 lg:grid-cols-5">
        {facts.map((fact) => (
          <div key={fact.label} className="min-w-0 px-3.5 py-2">
            <dt className={microLabel()}>{fact.label}</dt>
            <dd className={`tabular truncate text-[13px] ${fact.warn ? "font-medium text-danger" : ""}`}>{fact.value}</dd>
          </div>
        ))}
      </dl>

      <div className="flex justify-end">
        <Segmented
          label={t("sj.an.view")}
          value={view}
          onChange={setView}
          options={[
            { value: "chart", label: t("sj.an.viewChart") },
            { value: "table", label: t("sj.an.viewTable") },
          ]}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel
          id="an-scores"
          title={t("sj.an.scores")}
          description={t("sj.an.scoresHelp")}
          action={
            data.trend ? (
              <Badge tone={data.trend === "improving" ? "success" : data.trend === "declining" ? "warning" : "neutral"}>
                {data.trend === "improving" ? <TrendingUp className="h-3 w-3" aria-hidden /> : null}
                {data.trend === "declining" ? <TrendingDown className="h-3 w-3" aria-hidden /> : null}
                {t(`sj.an.trend.${data.trend}`)}
              </Badge>
            ) : undefined
          }
        >
          {noAttempts ? (
            <p className="px-3.5 py-6 text-sm text-muted">{t("sj.an.noAttempts")}</p>
          ) : view === "chart" ? (
            <>
              <ScoreChart attempts={data.attempts} />
              {data.trend === null ? <p className="border-t border-border px-3.5 py-2 text-xs text-muted">{t("sj.an.trendNeeds")}</p> : null}
            </>
          ) : (
            <Table caption={t("sj.an.scores")}>
              <THead>
                <tr>
                  <Th className="w-full">{t("sj.an.quiz")}</Th>
                  <Th>{t("sj.an.date")}</Th>
                  <Th align="right">{t("sj.an.score")}</Th>
                </tr>
              </THead>
              <TBody>
                {[...data.attempts].reverse().map((a) => (
                  <Tr key={a.attempt_id}>
                    <Td className="max-w-0 truncate">{a.quiz_title}</Td>
                    <Td className="whitespace-nowrap text-muted">{date(a.finished_at)}</Td>
                    <Td align="right" className="tabular whitespace-nowrap">
                      {percent(a.percent)}
                    </Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          )}
        </Panel>

        <Panel id="an-weeks" title={t("sj.an.weeks")} description={t("sj.an.weeksHelp")}>
          {!practised ? (
            <p className="px-3.5 py-6 text-sm text-muted">{t("sj.an.noWeeks")}</p>
          ) : view === "chart" ? (
            <WeeklyChart weeks={data.weeks} />
          ) : (
            <Table caption={t("sj.an.weeks")}>
              <THead>
                <tr>
                  <Th className="w-full">{t("sj.an.week")}</Th>
                  <Th align="right">{t("sj.an.quizzes")}</Th>
                  <Th align="right">{t("sj.col.answers")}</Th>
                  <Th align="right">{t("sj.col.accuracy")}</Th>
                </tr>
              </THead>
              <TBody>
                {[...data.weeks].reverse().map((w) => (
                  <Tr key={w.week_start}>
                    <Td className="whitespace-nowrap">{formatDay(w.week_start, locale, { day: "numeric", month: "short" })}</Td>
                    <Td align="right" className="tabular">
                      {w.attempts}
                    </Td>
                    <Td align="right" className="tabular">
                      {w.answers}
                    </Td>
                    <Td align="right" className="tabular">
                      {percent(w.accuracy)}
                    </Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          )}
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel id="an-types" title={t("sj.an.types")} description={t("sj.an.typesHelp")}>
          {data.by_type.length === 0 ? (
            <p className="px-3.5 py-5 text-sm text-muted">{t("sj.an.noTypes")}</p>
          ) : (
            <ul className="divide-y divide-border">
              {data.by_type.map((row) => {
                const name = t(`quiz.type.${row.qtype}` as "quiz.type.mcq");
                return (
                  <li key={row.qtype} className="flex items-center gap-3 px-3.5 py-2.5">
                    <span className="w-32 shrink-0 truncate text-[13px]">{name}</span>
                    <span className="min-w-0 flex-1">
                      <ProgressBar
                        value={row.accuracy ?? 0}
                        label={t("sj.progress.accuracyOf", { name })}
                        tone={row.accuracy !== null && row.accuracy < 0.8 ? "warning" : "success"}
                      />
                    </span>
                    <span className="tabular w-10 shrink-0 text-right text-[13px]">{percent(row.accuracy)}</span>
                    <span className="tabular hidden w-20 shrink-0 text-right text-xs text-muted sm:block">
                      {t("sj.progress.answers", { count: row.answers })}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>

        <Panel id="an-measure" title={t("sj.an.how")} description={t("sj.an.howHelp")}>
          <ul className="divide-y divide-border">
            {data.progress_parts.map((part) => (
              <li key={part.key} className="flex items-center gap-3 px-3.5 py-2.5">
                <span className="w-32 shrink-0 truncate text-[13px]">{t(`sj.an.part.${part.key}`)}</span>
                <span className="min-w-0 flex-1">
                  {part.value === null ? (
                    <span className="text-xs text-muted">{t("sj.an.noData")}</span>
                  ) : (
                    <ProgressBar value={part.value} label={t(`sj.an.part.${part.key}`)} />
                  )}
                </span>
                <span className="tabular w-10 shrink-0 text-right text-[13px]">{part.value === null ? "—" : percent(part.value)}</span>
                <span className="tabular hidden w-20 shrink-0 text-right text-xs text-muted sm:block">
                  {part.value === null ? "" : t("sj.an.weight", { weight: Math.round(part.weight * 100) })}
                </span>
              </li>
            ))}
          </ul>
          <p className="border-t border-border px-3.5 py-2 text-xs text-muted">
            {data.progress === null ? t("sj.an.notMeasuredWhy") : t("sj.an.measuredNote")}
          </p>
        </Panel>
      </div>

      {noAttempts && !practised && (progress.data?.documents.length ?? 0) === 0 ? (
        <p className="flex items-center gap-2 text-sm text-muted">
          <BarChart3 className="h-4 w-4" aria-hidden />
          {t("sj.an.startHint")}
        </p>
      ) : (
        <ProgressTab progress={progress} subjectId={subjectId} onOpenDoc={onOpenDoc} onOpenModule={onOpenModule} onAsk={onAsk} />
      )}
    </div>
  );
}
