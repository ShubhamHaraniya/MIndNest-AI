"use client";

import { Badge, type Tone } from "@/components/kit/badge";
import { ProgressBar } from "@/components/kit/progress";
import { useT } from "@/i18n/client";
import { formatMetric, modeLabelKey, runName } from "@/lib/eval";
import type { EvalRun, EvalStatus } from "@/lib/types";

const STATUS_TONE: Record<EvalStatus, Tone> = {
  queued: "neutral",
  running: "info",
  completed: "success",
  failed: "danger",
  cancelled: "neutral",
};

export function StatusBadge({ status }: { status: EvalStatus }) {
  const t = useT();
  return <Badge tone={STATUS_TONE[status]}>{t(`eval.status.${status}`)}</Badge>;
}

/** "3 of 50 questions" with a thin bar. */
export function RunProgress({ run, className }: { run: Pick<EvalRun, "done" | "total">; className?: string }) {
  const t = useT();
  const value = run.total > 0 ? run.done / run.total : 0;
  return (
    <div className={className}>
      <ProgressBar value={value} label={t("eval.runPage.progress", { done: run.done, total: run.total })} />
      <p className="tabular mt-1 text-xs text-muted">{t("eval.runPage.progress", { done: run.done, total: run.total })}</p>
    </div>
  );
}

export function useRunName(): (run: EvalRun) => string {
  const t = useT();
  return (run) => runName(run, t(modeLabelKey(run.config.mode)));
}

const LANGUAGE_ORDER = ["en", "hi", "gu"] as const;
export { LANGUAGE_ORDER };

/** A small "en 97% · hi 92% · gu 100%" line under an overall score. */
export function LanguageScores({ run, metric }: { run: EvalRun; metric: string }) {
  const byLanguage = run.summary?.by_language;
  if (!byLanguage) return null;
  const parts = LANGUAGE_ORDER.filter((code) => byLanguage[code]?.metrics[metric] !== undefined).map(
    (code) => `${code} ${formatMetric(metric, byLanguage[code]?.metrics[metric])}`,
  );
  if (parts.length < 2) return null;
  return <span className="tabular mt-0.5 block text-xs font-normal text-muted">{parts.join(" · ")}</span>;
}

/** How long a finished run took, "2 min 10 s"; empty while it has not finished. */
export function runDuration(run: EvalRun): string | null {
  if (!run.started_at || !run.finished_at) return null;
  const seconds = Math.max(0, Math.round((Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000));
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${seconds % 60} s`;
}
