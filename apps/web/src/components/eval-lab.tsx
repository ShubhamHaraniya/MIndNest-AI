"use client";

import { FileUp, Play } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { CompareTab } from "@/components/eval/compare-tab";
import { DatasetsTab } from "@/components/eval/datasets-tab";
import { MetricGlossary } from "@/components/eval/glossary";
import { ImportDialog } from "@/components/eval/import-dialog";
import { RunDialog } from "@/components/eval/run-dialog";
import { RunsTab } from "@/components/eval/runs-tab";
import { Button } from "@/components/kit/button";
import { ErrorState } from "@/components/kit/states";
import { Skeleton } from "@/components/kit/skeleton";
import { Tabs } from "@/components/kit/tabs";
import { useToast } from "@/components/kit/toast";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { isActive } from "@/lib/eval";
import type { EvalDataset, EvalRun, Subject } from "@/lib/types";

export { RunProgress, StatusBadge } from "@/components/eval/parts";

const POLL_MS = 3000;
type Tab = "runs" | "datasets" | "compare" | "scores";

/** The Evaluation Lab: question sets, runs, side-by-side comparison and a glossary of the scores. */
export function EvalLab({ subjects, openRunFor = null }: { subjects: Subject[]; openRunFor?: string | null }) {
  const t = useT();
  const toast = useToast();
  const [datasets, setDatasets] = useState<EvalDataset[] | null>(null);
  const [runs, setRuns] = useState<EvalRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("runs");
  const [selected, setSelected] = useState<string[]>([]);
  const [importing, setImporting] = useState(false);
  const [starting, setStarting] = useState<{ dataset: string } | null>(openRunFor ? { dataset: openRunFor } : null);

  const load = useCallback(async () => {
    try {
      const [loadedDatasets, loadedRuns] = await Promise.all([
        api<EvalDataset[]>("/eval/datasets"),
        api<EvalRun[]>("/eval/runs"),
      ]);
      setDatasets(loadedDatasets);
      setRuns(loadedRuns);
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const anyActive = runs?.some((run) => isActive(run.status)) ?? false;
  useEffect(() => {
    if (!anyActive) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [anyActive, load]);

  // Runs that were deleted drop out of the selection; the order of ticking is kept.
  const chosen = useMemo(() => {
    const byId = new Map((runs ?? []).map((run) => [run.id, run]));
    return selected.map((id) => byId.get(id)).filter((run): run is EvalRun => run !== undefined);
  }, [runs, selected]);

  function toggle(id: string) {
    setSelected((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current, id]));
  }

  if (error && (!datasets || !runs)) return <ErrorState compact description={error} onRetry={() => void load()} />;
  if (!datasets || !runs) {
    return (
      <div className="space-y-3" aria-hidden>
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs<Tab>
          label={t("nav.eval")}
          value={tab}
          onChange={setTab}
          className="min-w-0 flex-1"
          items={[
            { id: "runs", label: t("eval.runs.title"), count: runs.length },
            { id: "datasets", label: t("eval.datasets.title"), count: datasets.length },
            { id: "compare", label: t("eval.compare.title"), count: chosen.length > 0 ? chosen.length : undefined },
            { id: "scores", label: t("evx.tab.scores") },
          ]}
        />
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setImporting(true)}>
            <FileUp className="h-4 w-4" aria-hidden />
            {t("eval.datasets.import")}
          </Button>
          <Button onClick={() => setStarting({ dataset: "" })} disabled={datasets.length === 0}>
            <Play className="h-4 w-4" aria-hidden />
            {t("evx.newRun")}
          </Button>
        </div>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}

      {tab === "runs" ? (
        <RunsTab
          runs={runs}
          datasets={datasets}
          selected={chosen.map((run) => run.id)}
          onToggle={toggle}
          onCompare={() => setTab("compare")}
          onNewRun={() => setStarting({ dataset: "" })}
          onChanged={load}
        />
      ) : null}
      {tab === "datasets" ? (
        <DatasetsTab
          datasets={datasets}
          onImport={() => setImporting(true)}
          onRun={(id) => setStarting({ dataset: id })}
          onChanged={load}
        />
      ) : null}
      {tab === "compare" ? (
        <CompareTab runs={chosen} onRemove={toggle} onBack={() => setTab("runs")} />
      ) : null}
      {tab === "scores" ? (
        <div className="space-y-3">
          <p className="max-w-3xl text-[13px] text-muted">{t("eval.help")}</p>
          <MetricGlossary />
        </div>
      ) : null}

      <ImportDialog
        open={importing}
        subjects={subjects}
        onClose={() => setImporting(false)}
        onDone={(dataset) => {
          setImporting(false);
          toast.success(t("eval.import.done", { name: dataset.name, count: dataset.cases }));
          setTab("datasets");
          void load();
        }}
      />
      <RunDialog
        open={starting !== null}
        datasets={datasets}
        initialDataset={starting?.dataset ?? ""}
        onClose={() => setStarting(null)}
        onStarted={(count) => {
          setStarting(null);
          toast.success(t("eval.run.started", { count }));
          setTab("runs");
          void load();
        }}
      />
    </div>
  );
}
