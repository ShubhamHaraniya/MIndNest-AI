"use client";

import clsx from "clsx";
import { GitCompare, X } from "lucide-react";
import { Fragment } from "react";

import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { Panel } from "@/components/kit/panel";
import { EmptyState } from "@/components/kit/states";
import { Table, TBody, THead, Td, Th, Tr } from "@/components/kit/table";
import { useT } from "@/i18n/client";
import { ALL_METRICS, formatDelta, formatMetric, formatMs, type MetricDef } from "@/lib/eval";
import type { EvalRun } from "@/lib/types";

import { MetricGlossary } from "./glossary";
import { LANGUAGE_ORDER, useRunName } from "./parts";

const LANGUAGE_METRICS = ["recall_at_k", "mrr", "correctness", "faithfulness", "abstain"];

/** Two or more runs side by side. The first one is the baseline: every other column shows how far
 *  it moved from it, in percentage points, green when better and red when worse. */
export function CompareTab({
  runs,
  onRemove,
  onBack,
}: {
  runs: EvalRun[];
  onRemove: (id: string) => void;
  onBack: () => void;
}) {
  const t = useT();
  const name = useRunName();

  if (runs.length < 2) {
    return (
      <EmptyState icon={GitCompare} title={t("evx.compare.emptyTitle")} description={t("evx.compare.emptyBody")}>
        <Button onClick={onBack}>{t("evx.compare.choose")}</Button>
      </EmptyState>
    );
  }

  const sameSet = new Set(runs.map((run) => run.dataset_id)).size <= 1;
  const unfinished = runs.some((run) => !run.summary);
  const rows = ALL_METRICS.filter((metric) => runs.some((run) => run.summary?.metrics[metric.key] !== undefined));
  const languages = LANGUAGE_ORDER.filter((code) => runs.some((run) => run.summary?.by_language?.[code]));

  function cells(metric: MetricDef, read: (run: EvalRun) => number | undefined) {
    const values = runs.map(read);
    const known = values.filter((v): v is number => v !== undefined);
    const best = known.length > 1 ? (metric.lowerIsBetter ? Math.min(...known) : Math.max(...known)) : undefined;
    const base = values[0];
    return runs.map((run, index) => {
      const value = values[index];
      const diff = value !== undefined && base !== undefined && index > 0 ? value - base : 0;
      const good = metric.lowerIsBetter ? diff < 0 : diff > 0;
      const isBest = best !== undefined && value !== undefined && Math.abs(value - best) < 0.0005 && known.some((v) => Math.abs(v - best) > 0.0005);
      return (
        <Td key={run.id} align="right" className="tabular whitespace-nowrap">
          <span className={clsx(isBest && "font-semibold text-ink")}>{formatMetric(metric.key, value)}</span>
          {index > 0 && value !== undefined && base !== undefined ? (
            <span className={clsx("ml-1.5 text-xs", Math.abs(diff) < 0.0005 ? "text-muted" : good ? "text-success" : "text-danger")}>
              {formatDelta(metric.key, value, base)}
            </span>
          ) : null}
        </Td>
      );
    });
  }

  const head = (
    <THead>
      <tr>
        <Th>{t("eval.compare.metric")}</Th>
        {runs.map((run, index) => (
          <Th key={run.id} align="right" className="normal-case tracking-normal">
            <span className="inline-flex items-center gap-1.5">
              {index === 0 ? <Badge tone="brand">{t("evx.compare.baseline")}</Badge> : null}
              <span className="max-w-[12rem] truncate text-[12px] font-medium text-ink" title={name(run)}>
                {name(run)}
              </span>
            </span>
          </Th>
        ))}
      </tr>
    </THead>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {runs.map((run) => (
          <span key={run.id} className="inline-flex items-center gap-1 rounded border border-border-strong bg-surface py-0.5 pl-2.5 pr-1 text-[13px]">
            <span className="max-w-[14rem] truncate">{name(run)}</span>
            <button
              type="button"
              onClick={() => onRemove(run.id)}
              aria-label={t("evx.compare.remove", { name: name(run) })}
              className="rounded p-1 text-muted hover:bg-surface-3 hover:text-ink"
            >
              <X className="h-3 w-3" aria-hidden />
            </button>
          </span>
        ))}
      </div>

      {!sameSet ? (
        <p role="status" className="rounded border border-warning/40 bg-warning-soft px-3 py-2 text-[13px]">
          {t("eval.compare.differentSets")}
        </p>
      ) : null}
      {unfinished ? (
        <p role="status" className="rounded border border-border bg-surface-2 px-3 py-2 text-[13px] text-muted">
          {t("evx.compare.unfinished")}
        </p>
      ) : null}
      <p className="text-xs text-muted">{t("eval.compare.hint")}</p>

      <Panel id="compare-overall" title={t("evx.compare.overall")}>
        <Table caption={t("eval.compare.title")}>
          {head}
          <TBody>
            {rows.map((metric) => (
              <Tr key={metric.key}>
                <Td>
                  {t(metric.label)}
                  {metric.lowerIsBetter ? <span className="block text-xs text-muted">{t("eval.lowerIsBetter")}</span> : null}
                </Td>
                {cells(metric, (run) => run.summary?.metrics[metric.key])}
              </Tr>
            ))}
            <Tr>
              <Td>{t("eval.latency.retrieval")}</Td>
              {runs.map((run) => (
                <Td key={run.id} align="right" className="tabular whitespace-nowrap">
                  {formatMs(run.summary?.latency.retrieval_ms_p50)}
                  <span className="text-muted"> / {formatMs(run.summary?.latency.retrieval_ms_p95)}</span>
                </Td>
              ))}
            </Tr>
          </TBody>
        </Table>
      </Panel>

      {languages.length > 0 ? (
        <Panel id="compare-language" title={t("eval.compare.byLanguage")}>
          <Table caption={t("eval.compare.byLanguage")}>
            {head}
            <TBody>
              {languages.map((code) => {
                const metrics = ALL_METRICS.filter(
                  (m) =>
                    LANGUAGE_METRICS.includes(m.key) &&
                    runs.some((run) => run.summary?.by_language?.[code]?.metrics[m.key] !== undefined),
                );
                return (
                  <Fragment key={code}>
                    <tr className="bg-surface-2">
                      <td colSpan={runs.length + 1} className="px-3.5 py-1.5 text-xs font-semibold text-muted">
                        {t(`eval.lang.${code}`)} · {runs[0]?.summary?.by_language?.[code]?.cases ?? 0} {t("eval.compare.questions")}
                      </td>
                    </tr>
                    {metrics.map((metric) => (
                      <Tr key={`${code}-${metric.key}`}>
                        <Td>{t(metric.label)}</Td>
                        {cells(metric, (run) => run.summary?.by_language?.[code]?.metrics[metric.key])}
                      </Tr>
                    ))}
                  </Fragment>
                );
              })}
            </TBody>
          </Table>
        </Panel>
      ) : null}

      <MetricGlossary only={new Set(rows.map((m) => m.key))} />
    </div>
  );
}
