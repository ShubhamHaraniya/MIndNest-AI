import type { MessageKey } from "@/i18n/translate";

import type { EvalMode, EvalRun, EvalStatus } from "./types";

export const MODES: EvalMode[] = ["baseline", "hybrid", "advanced"];

export type MetricDef = { key: string; label: MessageKey; about: MessageKey; lowerIsBetter?: boolean };
export type MetricGroup = { title: MessageKey; metrics: MetricDef[] };

export const METRIC_GROUPS: MetricGroup[] = [
  {
    title: "eval.group.retrieval",
    metrics: [
      { key: "recall_at_1", label: "eval.metric.recall_at_1", about: "evx.about.recall_at_1" },
      { key: "recall_at_3", label: "eval.metric.recall_at_3", about: "evx.about.recall_at_3" },
      { key: "recall_at_k", label: "eval.metric.recall_at_k", about: "evx.about.recall_at_k" },
      { key: "precision_at_k", label: "eval.metric.precision_at_k", about: "evx.about.precision_at_k" },
      { key: "hit_at_k", label: "eval.metric.hit_at_k", about: "evx.about.hit_at_k" },
      { key: "mrr", label: "eval.metric.mrr", about: "evx.about.mrr" },
    ],
  },
  {
    title: "eval.group.answers",
    metrics: [
      { key: "correctness", label: "eval.metric.correctness", about: "evx.about.correctness" },
      { key: "faithfulness", label: "eval.metric.faithfulness", about: "evx.about.faithfulness" },
      { key: "relevance", label: "eval.metric.relevance", about: "evx.about.relevance" },
      { key: "cited_any", label: "eval.metric.cited_any", about: "evx.about.cited_any" },
      { key: "citation_validity", label: "eval.metric.citation_validity", about: "evx.about.citation_validity" },
      { key: "citation_accuracy", label: "eval.metric.citation_accuracy", about: "evx.about.citation_accuracy" },
    ],
  },
  {
    title: "eval.group.safety",
    metrics: [
      { key: "abstain", label: "eval.metric.abstain", about: "evx.about.abstain" },
      { key: "false_refusal", label: "eval.metric.false_refusal", lowerIsBetter: true, about: "evx.about.false_refusal" },
      { key: "injection_leaked", label: "eval.metric.injection_leaked", lowerIsBetter: true, about: "evx.about.injection_leaked" },
    ],
  },
];

export const ALL_METRICS: MetricDef[] = METRIC_GROUPS.flatMap((group) => group.metrics);

export function isActive(status: EvalStatus): boolean {
  return status === "queued" || status === "running";
}

/** Scores are 0..1. MRR reads best as a plain decimal, everything else as a percentage. */
export function formatMetric(key: string, value: number | undefined | null): string {
  if (value === undefined || value === null) return "–";
  return key === "mrr" ? value.toFixed(2) : `${Math.round(value * 100)}%`;
}

/** The change from `base` to `value`, in percentage points (or MRR units). */
export function formatDelta(key: string, value: number, base: number): string {
  const diff = value - base;
  if (Math.abs(diff) < 0.0005) return "±0";
  const sign = diff > 0 ? "+" : "−";
  const size = Math.abs(diff);
  return key === "mrr" ? `${sign}${size.toFixed(2)}` : `${sign}${(size * 100).toFixed(1)}`;
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
}

export function modeLabelKey(mode: EvalMode): MessageKey {
  return `eval.mode.short.${mode}` as MessageKey;
}

export function runName(run: EvalRun, shortMode: string): string {
  const extra = run.config.generate ? " + AI" : "";
  return run.label ? `${run.label} (${shortMode}${extra})` : `${shortMode}${extra}`;
}
