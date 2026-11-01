"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Button } from "@/components/kit/button";
import { FormRow, Input, Select } from "@/components/kit/controls";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { MODES } from "@/lib/eval";
import type { EvalDataset, EvalMode, EvalRun } from "@/lib/types";

/** Start one run for each search method that is ticked. Search-only runs cost nothing; writing
 *  answers uses the student's own AI key. */
export function RunDialog({
  open,
  datasets,
  initialDataset,
  onClose,
  onStarted,
}: {
  open: boolean;
  datasets: EvalDataset[];
  initialDataset: string;
  onClose: () => void;
  onStarted: (count: number) => void;
}) {
  const t = useT();
  const [datasetId, setDatasetId] = useState("");
  const [modes, setModes] = useState<EvalMode[]>([...MODES]);
  const [generate, setGenerate] = useState(false);
  const [judge, setJudge] = useState(false);
  const [label, setLabel] = useState("");
  const [topK, setTopK] = useState("");
  const [candidates, setCandidates] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDatasetId(datasets.some((d) => d.id === initialDataset) ? initialDataset : (datasets[0]?.id ?? ""));
    setModes([...MODES]);
    setGenerate(false);
    setJudge(false);
    setLabel("");
    setTopK("");
    setCandidates("");
    setMessage(null);
    setBusy(false);
    // Only when the dialog opens: later reloads of the list must not reset what was typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const dataset = datasets.find((d) => d.id === datasetId);

  function toggle(mode: EvalMode) {
    setModes((current) => (current.includes(mode) ? current.filter((m) => m !== mode) : [...current, mode]));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setMessage(null);
    if (!datasetId) return setMessage(t("eval.run.needDataset"));
    if (modes.length === 0) return setMessage(t("eval.run.needMode"));
    setBusy(true);
    try {
      const started = await api<EvalRun[]>("/eval/runs", {
        method: "POST",
        body: {
          dataset_id: datasetId,
          modes: MODES.filter((mode) => modes.includes(mode)),
          generate,
          judge: generate && judge,
          label: label.trim() || null,
          top_k: topK.trim() ? Number(topK) : null,
          candidates: candidates.trim() ? Number(candidates) : null,
        },
      });
      onStarted(started.length);
    } catch (caught) {
      setMessage(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("eval.run.title")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        <FormRow label={t("eval.run.dataset")} htmlFor="run-dataset">
          <Select id="run-dataset" value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} ({t("eval.datasets.count", { count: d.cases })})
              </option>
            ))}
          </Select>
        </FormRow>
        <FormRow label={t("eval.run.label")} htmlFor="run-label" hint={t("evx.run.labelHint")}>
          <Input id="run-label" value={label} maxLength={80} onChange={(event) => setLabel(event.target.value)} />
        </FormRow>

        <div className="grid gap-3 sm:grid-cols-2">
          <FormRow label={t("evx.run.topK")} htmlFor="run-top-k" hint={t("evx.run.topKHint")}>
            <Input
              id="run-top-k"
              type="number"
              inputMode="numeric"
              min={1}
              max={20}
              placeholder="6"
              value={topK}
              onChange={(event) => setTopK(event.target.value)}
            />
          </FormRow>
          <FormRow label={t("evx.run.candidates")} htmlFor="run-candidates" hint={t("evx.run.candidatesHint")}>
            <Input
              id="run-candidates"
              type="number"
              inputMode="numeric"
              min={5}
              max={100}
              placeholder="30"
              value={candidates}
              onChange={(event) => setCandidates(event.target.value)}
            />
          </FormRow>
        </div>

        <fieldset>
          <legend className="mb-1 text-[13px] font-medium">{t("eval.run.modes")}</legend>
          <div className="space-y-1.5">
            {MODES.map((mode) => (
              <label key={mode} className="flex items-center gap-2 text-[13px]">
                <input
                  type="checkbox"
                  checked={modes.includes(mode)}
                  onChange={() => toggle(mode)}
                  className="h-4 w-4 accent-primary"
                />
                {t(`eval.mode.${mode}`)}
              </label>
            ))}
          </div>
        </fieldset>

        <div className="space-y-2">
          <label className="flex items-start gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={generate}
              onChange={(event) => setGenerate(event.target.checked)}
              className="mt-0.5 h-4 w-4 accent-primary"
            />
            <span>
              {t("eval.run.generate")}
              <span className="block text-xs text-muted">{t("eval.run.generateHint")}</span>
            </span>
          </label>
          <label className={`ml-6 flex items-start gap-2 text-[13px] ${generate ? "" : "opacity-50"}`}>
            <input
              type="checkbox"
              checked={generate && judge}
              disabled={!generate}
              onChange={(event) => setJudge(event.target.checked)}
              className="mt-0.5 h-4 w-4 accent-primary"
            />
            <span>
              {t("eval.run.judge")}
              <span className="block text-xs text-muted">{t("eval.run.judgeHint")}</span>
            </span>
          </label>
        </div>

        {dataset && modes.length > 0 ? (
          <p className="rounded border border-border bg-surface-2 px-3 py-2 text-xs text-muted">
            {t(generate ? "evx.run.summaryAi" : "evx.run.summary", { runs: modes.length, questions: dataset.cases })}
          </p>
        ) : null}

        {message ? (
          <p role="alert" className="text-sm text-danger">
            {message}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy} disabled={!datasetId}>
            {t("eval.run.start")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
