"use client";

import { CheckCircle2, ChevronDown, Download, XCircle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { StatusBadge, runDuration, useRunName, RunProgress } from "@/components/eval/parts";
import { Badge } from "@/components/kit/badge";
import { Breadcrumbs } from "@/components/kit/breadcrumbs";
import { Button } from "@/components/kit/button";
import { SearchField, Segmented, Select } from "@/components/kit/controls";
import { Panel, Facts } from "@/components/kit/panel";
import { Popover } from "@/components/kit/popover";
import { ProgressBar } from "@/components/kit/progress";
import { Skeleton } from "@/components/kit/skeleton";
import { EmptyState, ErrorState, NoResults } from "@/components/kit/states";
import { Table, TBody, THead, Td, Th, Tr } from "@/components/kit/table";
import { useToast } from "@/components/kit/toast";
import { Alert } from "@/components/ui";
import { useLocale, useT } from "@/i18n/client";
import { ApiError, api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { METRIC_GROUPS, formatMetric, formatMs, isActive } from "@/lib/eval";
import { relativeTime } from "@/lib/format";
import type { EvalResult, EvalRun } from "@/lib/types";

const POLL_MS = 3000;
type Filter = "all" | "problems";

function isProblem(result: EvalResult): boolean {
  const s = result.scores;
  return (
    result.error !== null ||
    (result.answerable && s.hit_at_k === 0) ||
    (s.correctness !== undefined && s.correctness < 0.6) ||
    s.false_refusal === 1 ||
    s.abstain === 0 ||
    s.injection_leaked === 1
  );
}

type ExportFormat = "json" | "questions_csv" | "passages_csv";
const EXPORTS: { format: ExportFormat; label: "eval.download.json" | "eval.download.questions" | "eval.download.passages" }[] = [
  { format: "json", label: "eval.download.json" },
  { format: "questions_csv", label: "eval.download.questions" },
  { format: "passages_csv", label: "eval.download.passages" },
];

/** Saves one of the run's export files. The file name comes from the server's response. */
async function saveExport(runId: string, format: ExportFormat): Promise<void> {
  const response = await fetch(`/api/v1/eval/runs/${runId}/export?format=${format}`, { credentials: "same-origin" });
  if (!response.ok) throw new Error(String(response.status));
  const header = response.headers.get("content-disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(header)?.[1] ?? `mindnest-eval-${runId.slice(0, 8)}.${format === "json" ? "json" : "csv"}`;
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function DownloadMenu({ runId }: { runId: string }) {
  const t = useT();
  const toast = useToast();
  const [busy, setBusy] = useState<ExportFormat | null>(null);

  async function run(format: ExportFormat, close: () => void) {
    setBusy(format);
    try {
      await saveExport(runId, format);
      close();
    } catch {
      toast.error(t("eval.download.failed"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Popover
      label={t("eval.download.title")}
      align="end"
      side="bottom"
      panelClassName="w-72 p-2"
      trigger={({ toggle, open, id }) => (
        <Button variant="secondary" data-popover-trigger aria-expanded={open} aria-controls={open ? id : undefined} onClick={toggle}>
          <Download className="h-4 w-4" aria-hidden />
          {t("eval.download.title")}
          <ChevronDown className="h-3.5 w-3.5" aria-hidden />
        </Button>
      )}
    >
      {(close) => (
        <div className="space-y-1">
          <p className="px-1 pb-1 text-xs text-muted">{t("eval.download.hint")}</p>
          {EXPORTS.map((item) => (
            <Button
              key={item.format}
              variant="ghost"
              size="sm"
              className="w-full justify-start"
              loading={busy === item.format}
              onClick={() => void run(item.format, close)}
            >
              {t(item.label)}
            </Button>
          ))}
        </div>
      )}
    </Popover>
  );
}

export function EvalRunView({ runId }: { runId: string }) {
  const t = useT();
  const locale = useLocale();
  const name = useRunName();
  const [run, setRun] = useState<EvalRun | null>(null);
  const [results, setResults] = useState<EvalResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [stopping, setStopping] = useState(false);

  const load = useCallback(async () => {
    try {
      const loaded = await api<EvalRun>(`/eval/runs/${runId}`);
      setRun(loaded);
      setResults(await api<EvalResult[]>(`/eval/runs/${runId}/results`));
      setError(null);
    } catch (caught) {
      if (caught instanceof ApiError && (caught.status === 404 || caught.status === 422)) setMissing(true);
      else setError(errorMessage(caught, t));
    }
  }, [runId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const active = run ? isActive(run.status) : false;
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [active, load]);

  async function stop() {
    setStopping(true);
    try {
      setRun(await api<EvalRun>(`/eval/runs/${runId}/cancel`, { method: "POST" }));
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setStopping(false);
    }
  }

  const crumbs = (last: string) => (
    <Breadcrumbs
      label={t("common.breadcrumb")}
      items={[{ label: t("nav.eval"), href: "/eval" }, { label: t("eval.runs.title"), href: "/eval" }, { label: last }]}
    />
  );

  if (missing) {
    return (
      <>
        {crumbs(t("eval.runPage.notFound"))}
        <EmptyState title={t("eval.runPage.notFound")} description={t("evx.runPage.notFoundBody")}>
          <Link href="/eval" className="text-sm font-medium text-brand hover:underline">
            {t("eval.runPage.back")}
          </Link>
        </EmptyState>
      </>
    );
  }
  if (!run) {
    return (
      <>
        {crumbs(t("common.loading"))}
        {error ? (
          <ErrorState compact description={error} onRetry={() => void load()} />
        ) : (
          <div className="space-y-3" aria-hidden>
            <Skeleton className="h-8 w-1/2" />
            <Skeleton className="h-40 w-full" />
          </div>
        )}
      </>
    );
  }

  const summary = run.summary;
  const title = name(run);
  const answersKey = run.config.judge ? "eval.runPage.graded" : run.config.generate ? "eval.runPage.withAnswers" : "eval.runPage.searchOnly";
  const failureText = run.error
    ? t(
        (["invalid_key", "no_provider_key", "key_unreadable"].includes(run.error)
          ? `eval.runError.${run.error}`
          : "eval.runError.internal") as "eval.runError.internal",
      )
    : null;

  return (
    <>
      {crumbs(title)}
      <header className="mb-4 flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 className="font-display flex flex-wrap items-center gap-3 text-2xl leading-tight">
            <span className="min-w-0 break-words">{title}</span>
            <StatusBadge status={run.status} />
          </h1>
          <p className="mt-0.5 text-[13px] text-muted">{run.dataset_name}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {active ? (
            <Button variant="secondary" loading={stopping} onClick={() => void stop()}>
              {t("eval.runPage.cancel")}
            </Button>
          ) : null}
          {run.done > 0 ? <DownloadMenu runId={run.id} /> : null}
        </div>
      </header>

      <div className="space-y-4">
        {error ? <Alert>{error}</Alert> : null}
        {failureText ? <Alert>{failureText}</Alert> : null}
        {summary && summary.degraded > 0 ? <Alert tone="info">{t("eval.runPage.degraded", { count: summary.degraded })}</Alert> : null}
        {summary && summary.failed > 0 ? <Alert tone="info">{t("eval.runPage.failedCases", { count: summary.failed })}</Alert> : null}

        <Panel id="run-facts" title={t("evx.runPage.about")} bodyClassName="px-3.5 py-3">
          <Facts
            className="sm:grid-cols-2 lg:grid-cols-4"
            items={[
              { label: t("eval.run.dataset"), value: <Link href={`/eval/datasets/${run.dataset_id}`} className="text-brand hover:underline">{run.dataset_name}</Link> },
              { label: t("evx.runPage.method"), value: t(`eval.mode.short.${run.config.mode}`) },
              { label: t("evx.runPage.passages"), value: String(run.config.top_k) },
              { label: t("evx.runPage.answers"), value: t(answersKey) },
              { label: t("evx.runPage.model"), value: run.config.model ?? "–" },
              { label: t("evx.col.started"), value: run.started_at ? relativeTime(run.started_at, locale) : "–" },
              { label: t("evx.runPage.took"), value: runDuration(run) ?? "–" },
              { label: t("evx.runPage.questions"), value: String(run.total) },
            ]}
          />
          {active ? <RunProgress run={run} className="mt-3 max-w-md" /> : null}
        </Panel>

        {summary ? <Scores run={run} /> : active ? null : <EmptyState compact title={t("evx.runPage.noScores")} description={t("evx.runPage.noScoresBody")} />}

        <Results results={results} />
      </div>
    </>
  );
}

function Scores({ run }: { run: EvalRun }) {
  const t = useT();
  const summary = run.summary;
  if (!summary) return null;
  const latency = summary.latency;
  const languageColumns = ["recall_at_k", "mrr", "correctness", "faithfulness", "abstain"].filter((key) =>
    Object.values(summary.by_language).some((entry) => entry.metrics[key] !== undefined),
  );
  const languageMetric = (key: string) => METRIC_GROUPS.flatMap((g) => g.metrics).find((m) => m.key === key);

  return (
    <>
      <Panel id="run-scores" title={t("evx.runPage.scores")} description={t("evx.runPage.scoresHint")}>
        <Table caption={t("evx.runPage.scores")}>
          <THead>
            <tr>
              <Th>{t("eval.compare.metric")}</Th>
              <Th align="right">{t("evx.runPage.score")}</Th>
              <Th className="hidden w-40 sm:table-cell">
                <span className="sr-only">{t("evx.runPage.bar")}</span>
              </Th>
              <Th className="hidden lg:table-cell">{t("evx.runPage.means")}</Th>
            </tr>
          </THead>
          <TBody>
            {METRIC_GROUPS.map((group) => {
              const present = group.metrics.filter((metric) => summary.metrics[metric.key] !== undefined);
              if (present.length === 0) return null;
              return (
                <GroupRows key={group.title} title={t(group.title)}>
                  {present.map((metric) => {
                    const value = summary.metrics[metric.key] ?? 0;
                    return (
                      <Tr key={metric.key}>
                        <Td>
                          {t(metric.label)}
                          {metric.lowerIsBetter ? <span className="block text-xs text-muted">{t("eval.lowerIsBetter")}</span> : null}
                        </Td>
                        <Td align="right" className="tabular text-base font-semibold">
                          {formatMetric(metric.key, value)}
                        </Td>
                        <Td className="hidden sm:table-cell">
                          <ProgressBar value={value} label={t(metric.label)} tone={metric.lowerIsBetter ? "warning" : "brand"} />
                        </Td>
                        <Td className="hidden max-w-md text-xs text-muted lg:table-cell">{t(metric.about)}</Td>
                      </Tr>
                    );
                  })}
                </GroupRows>
              );
            })}
          </TBody>
        </Table>
      </Panel>

      <Panel id="run-speed" title={t("eval.group.speed")} bodyClassName="px-3.5 py-3">
        <Facts
          className="sm:grid-cols-2 lg:grid-cols-4"
          items={[
            { label: t("eval.latency.retrieval"), value: `${formatMs(latency.retrieval_ms_p50)} / ${formatMs(latency.retrieval_ms_p95)}` },
            ...(run.config.generate
              ? [
                  { label: t("eval.latency.firstToken"), value: `${formatMs(latency.first_token_ms_p50)} / ${formatMs(latency.first_token_ms_p95)}` },
                  { label: t("eval.latency.answer"), value: `${formatMs(latency.answer_ms_p50)} / ${formatMs(latency.answer_ms_p95)}` },
                  { label: t("eval.tokens"), value: String(summary.est_tokens_avg ?? "–") },
                ]
              : []),
          ]}
        />
      </Panel>

      {Object.keys(summary.by_language).length > 1 ? (
        <Panel id="run-language" title={t("eval.runPage.byLanguage")}>
          <Table caption={t("eval.runPage.byLanguage")}>
            <THead>
              <tr>
                <Th>{t("common.language")}</Th>
                <Th align="right">{t("evx.runPage.questions")}</Th>
                {languageColumns.map((key) => {
                  const def = languageMetric(key);
                  return (
                    <Th key={key} align="right">
                      {def ? t(def.label) : key}
                    </Th>
                  );
                })}
              </tr>
            </THead>
            <TBody>
              {Object.entries(summary.by_language).map(([code, entry]) => (
                <Tr key={code}>
                  <Td className="font-medium">{t(`eval.lang.${code as "en" | "hi" | "gu"}`)}</Td>
                  <Td align="right" className="tabular">
                    {entry.cases}
                  </Td>
                  {languageColumns.map((key) => (
                    <Td key={key} align="right" className="tabular">
                      {formatMetric(key, entry.metrics[key])}
                    </Td>
                  ))}
                </Tr>
              ))}
            </TBody>
          </Table>
        </Panel>
      ) : null}
    </>
  );
}

function GroupRows({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <>
      <tr className="bg-surface-2">
        <th colSpan={4} scope="colgroup" className="px-3.5 py-1.5 text-left text-xs font-semibold text-muted">
          {title}
        </th>
      </tr>
      {children}
    </>
  );
}

function Results({ results }: { results: EvalResult[] }) {
  const t = useT();
  const [filter, setFilter] = useState<Filter>("all");
  const [language, setLanguage] = useState("");
  const [query, setQuery] = useState("");

  const problems = useMemo(() => results.filter(isProblem).length, [results]);
  const languages = useMemo(() => Array.from(new Set(results.map((r) => r.language))), [results]);
  const needle = query.trim().toLocaleLowerCase();
  const shown = results.filter((result) => {
    if (filter === "problems" && !isProblem(result)) return false;
    if (language && result.language !== language) return false;
    if (!needle) return true;
    return `${result.case_key} ${result.question}`.toLocaleLowerCase().includes(needle);
  });

  return (
    <section aria-labelledby="results-title" className="space-y-3">
      <h2 id="results-title" className="text-base font-semibold">
        {t("eval.results.title")}
      </h2>
      {results.length === 0 ? (
        <p className="text-sm text-muted">{t("eval.results.none")}</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <SearchField value={query} onChange={setQuery} placeholder={t("evx.results.search")} className="w-full sm:w-60" />
            {languages.length > 1 ? (
              <Select aria-label={t("common.language")} value={language} onChange={(event) => setLanguage(event.target.value)}>
                <option value="">{t("evx.results.allLanguages")}</option>
                {languages.map((code) => (
                  <option key={code} value={code}>
                    {t(`eval.lang.${code}`)}
                  </option>
                ))}
              </Select>
            ) : null}
            <Segmented
              label={t("eval.results.title")}
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: t("eval.results.filterAll"), count: results.length },
                { value: "problems", label: t("eval.results.filterProblems"), count: problems },
              ]}
            />
            <p className="tabular ml-auto text-xs text-muted">{t("evx.results.count", { shown: shown.length, total: results.length })}</p>
          </div>
          {shown.length === 0 ? (
            <NoResults title={t("evx.results.noMatch")} />
          ) : (
            <ul className="space-y-2">
              {shown.map((result) => (
                <ResultRow key={result.case_key} result={result} />
              ))}
            </ul>
          )}
        </>
      )}
      <p className="max-w-3xl text-xs text-muted">{t("eval.help")}</p>
    </section>
  );
}

function ResultRow({ result }: { result: EvalResult }) {
  const t = useT();
  const hit = result.scores.hit_at_k;
  return (
    <li>
      <details className="group rounded-card border border-border bg-surface">
        <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 px-3.5 py-2.5 text-[13px] hover:bg-surface-2">
          <span className="font-mono text-xs text-muted">{result.case_key}</span>
          <Badge>{t(`eval.lang.${result.language}`)}</Badge>
          <span className="min-w-0 flex-1 truncate">{result.question}</span>
          {!result.answerable ? (
            <Badge>{t("eval.dataset.notInMaterials")}</Badge>
          ) : hit === undefined ? null : hit === 1 ? (
            <Badge tone="success">
              <CheckCircle2 className="h-3 w-3" aria-hidden />
              {t("eval.result.hit")}
            </Badge>
          ) : (
            <Badge tone="danger">
              <XCircle className="h-3 w-3" aria-hidden />
              {t("eval.result.miss")}
            </Badge>
          )}
          {result.error ? <Badge tone="danger">{t("eval.result.error", { code: result.error })}</Badge> : null}
        </summary>
        <div className="space-y-4 border-t border-border px-3.5 py-3.5 text-[13px]">
          <p className="whitespace-pre-wrap break-words">{result.question}</p>
          {result.answerable ? (
            result.reference_answer ? (
              <Block title={t("eval.result.reference")}>{result.reference_answer}</Block>
            ) : null
          ) : (
            <p className="text-muted">{t("eval.result.notInMaterials")}</p>
          )}
          {result.answer ? <Block title={t("eval.result.answer")}>{result.answer}</Block> : null}
          <div>
            <h4 className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{t("eval.result.found")}</h4>
            {result.retrieved.length === 0 ? (
              <p className="mt-1 text-muted">{t("eval.result.noPassages")}</p>
            ) : (
              <ol className="mt-2 space-y-2">
                {result.retrieved.map((passage) => (
                  <li
                    key={passage.n}
                    className={
                      passage.relevant
                        ? "rounded border border-success/40 bg-success-soft px-3 py-2"
                        : "rounded border border-border bg-surface-2 px-3 py-2"
                    }
                  >
                    <p className="text-xs text-muted">
                      [{passage.n}] {passage.filename}
                      {passage.page !== null ? ` · ${t("eval.result.page", { page: passage.page })}` : ""}
                      {passage.relevant ? ` · ${t("eval.result.relevant")}` : ""}
                    </p>
                    <p className="mt-1 line-clamp-4 whitespace-pre-wrap break-words">{passage.text}</p>
                  </li>
                ))}
              </ol>
            )}
          </div>
          {Object.keys(result.scores).length > 0 ? (
            <p className="tabular text-xs text-muted">
              {Object.entries(result.scores)
                .map(([key, value]) => `${key} ${formatMetric(key, value)}`)
                .join(" · ")}
            </p>
          ) : null}
        </div>
      </details>
    </li>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{title}</h4>
      <p className="mt-1 whitespace-pre-wrap break-words">{children}</p>
    </div>
  );
}
