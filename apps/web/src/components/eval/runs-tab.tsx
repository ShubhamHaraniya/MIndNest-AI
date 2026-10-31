"use client";

import { GitCompare, Play, Trash2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Button } from "@/components/kit/button";
import { ConfirmDialog } from "@/components/kit/confirm";
import { SearchField, Segmented, Select } from "@/components/kit/controls";
import { EmptyState, NoResults } from "@/components/kit/states";
import { Table, TBody, THead, Td, Th, Tr } from "@/components/kit/table";
import { useToast } from "@/components/kit/toast";
import { IconButton } from "@/components/subjects/bits";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { formatMetric, isActive } from "@/lib/eval";
import { relativeTime } from "@/lib/format";
import type { EvalDataset, EvalRun } from "@/lib/types";

import { LanguageScores, RunProgress, StatusBadge, useRunName } from "./parts";

type StatusFilter = "all" | "active" | "done" | "problems";

/** Every run, newest first, with the headline scores. Tick two or more to compare them. */
export function RunsTab({
  runs,
  datasets,
  selected,
  onToggle,
  onCompare,
  onNewRun,
  onChanged,
}: {
  runs: EvalRun[];
  datasets: EvalDataset[];
  selected: string[];
  onToggle: (id: string) => void;
  onCompare: () => void;
  onNewRun: () => void;
  onChanged: () => Promise<void>;
}) {
  const t = useT();
  const locale = useLocale();
  const toast = useToast();
  const name = useRunName();
  const [query, setQuery] = useState("");
  const [datasetId, setDatasetId] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [removing, setRemoving] = useState<EvalRun | null>(null);

  const counts = useMemo(
    () => ({
      all: runs.length,
      active: runs.filter((r) => isActive(r.status)).length,
      done: runs.filter((r) => r.status === "completed").length,
      problems: runs.filter((r) => r.status === "failed" || r.status === "cancelled").length,
    }),
    [runs],
  );

  const needle = query.trim().toLocaleLowerCase();
  const shown = runs.filter((run) => {
    if (datasetId && run.dataset_id !== datasetId) return false;
    if (status === "active" && !isActive(run.status)) return false;
    if (status === "done" && run.status !== "completed") return false;
    if (status === "problems" && run.status !== "failed" && run.status !== "cancelled") return false;
    if (!needle) return true;
    return `${name(run)} ${run.dataset_name ?? ""}`.toLocaleLowerCase().includes(needle);
  });

  async function remove() {
    if (!removing) return;
    try {
      await api(`/eval/runs/${removing.id}`, { method: "DELETE" });
      toast.success(t("evx.runs.deleted"));
      await onChanged();
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  if (runs.length === 0) {
    return (
      <EmptyState icon={Play} title={t("evx.runs.emptyTitle")} description={t("evx.runs.emptyBody")}>
        <Button onClick={onNewRun} disabled={datasets.length === 0}>
          {t("evx.newRun")}
        </Button>
        {datasets.length === 0 ? <p className="w-full text-xs text-muted">{t("evx.runs.needDataset")}</p> : null}
      </EmptyState>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <SearchField value={query} onChange={setQuery} placeholder={t("evx.runs.search")} className="w-full sm:w-60" />
        <Select aria-label={t("eval.run.dataset")} value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>
          <option value="">{t("evx.runs.allDatasets")}</option>
          {datasets.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </Select>
        <Segmented
          label={t("eval.col.status")}
          value={status}
          onChange={setStatus}
          options={[
            { value: "all", label: t("evx.filter.all"), count: counts.all },
            { value: "active", label: t("evx.filter.active"), count: counts.active },
            { value: "done", label: t("evx.filter.done"), count: counts.done },
            { value: "problems", label: t("evx.filter.problems"), count: counts.problems },
          ]}
        />
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-muted">
            {selected.length >= 2 ? t("evx.runs.selected", { count: selected.length }) : t("evx.runs.pickTwo")}
          </span>
          <Button variant="secondary" size="sm" disabled={selected.length < 2} onClick={onCompare}>
            <GitCompare className="h-3.5 w-3.5" aria-hidden />
            {t("eval.runs.compare", { count: selected.length })}
          </Button>
        </div>
      </div>

      {shown.length === 0 ? (
        <NoResults title={t("evx.runs.noMatch")} />
      ) : (
        <div className="rounded-card border border-border bg-surface">
          <Table caption={t("eval.runs.title")}>
            <THead>
              <tr>
                <Th className="w-8">
                  <span className="sr-only">{t("eval.runs.select")}</span>
                </Th>
                <Th>{t("eval.col.run")}</Th>
                <Th>{t("eval.col.status")}</Th>
                <Th align="right">{t("eval.col.recall")}</Th>
                <Th align="right">{t("eval.col.mrr")}</Th>
                <Th align="right" className="hidden md:table-cell">
                  {t("eval.col.correct")}
                </Th>
                <Th align="right" className="hidden lg:table-cell">
                  {t("eval.col.faithful")}
                </Th>
                <Th className="hidden xl:table-cell">{t("evx.col.started")}</Th>
                <Th>
                  <span className="sr-only">{t("evx.col.actions")}</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {shown.map((run) => {
                const metrics = run.summary?.metrics ?? {};
                return (
                  <Tr key={run.id}>
                    <Td>
                      <input
                        type="checkbox"
                        aria-label={`${t("eval.runs.select")}: ${name(run)}`}
                        checked={selected.includes(run.id)}
                        onChange={() => onToggle(run.id)}
                        className="h-4 w-4 accent-primary"
                      />
                    </Td>
                    <Td className="max-w-[16rem]">
                      <Link href={`/eval/runs/${run.id}`} className="block truncate font-medium text-brand hover:underline" title={name(run)}>
                        {name(run)}
                      </Link>
                      <span className="block truncate text-xs text-muted">{run.dataset_name}</span>
                    </Td>
                    <Td className="min-w-[8rem]">
                      <StatusBadge status={run.status} />
                      {isActive(run.status) ? <RunProgress run={run} className="mt-1.5 w-32" /> : null}
                    </Td>
                    <Td align="right" className="tabular">
                      {formatMetric("recall_at_k", metrics.recall_at_k)}
                      <LanguageScores run={run} metric="recall_at_k" />
                    </Td>
                    <Td align="right" className="tabular">
                      {formatMetric("mrr", metrics.mrr)}
                      <LanguageScores run={run} metric="mrr" />
                    </Td>
                    <Td align="right" className="tabular hidden md:table-cell">
                      {formatMetric("correctness", metrics.correctness)}
                    </Td>
                    <Td align="right" className="tabular hidden lg:table-cell">
                      {formatMetric("faithfulness", metrics.faithfulness)}
                    </Td>
                    <Td className="hidden whitespace-nowrap text-muted xl:table-cell">{relativeTime(run.created_at, locale)}</Td>
                    <Td align="right">
                      <IconButton label={`${t("common.delete")}: ${name(run)}`} danger onClick={() => setRemoving(run)}>
                        <Trash2 className="h-3.5 w-3.5" aria-hidden />
                      </IconButton>
                    </Td>
                  </Tr>
                );
              })}
            </TBody>
          </Table>
        </div>
      )}

      <ConfirmDialog
        open={removing !== null}
        title={t("evx.runs.deleteTitle")}
        description={t("eval.runs.deleteConfirm")}
        confirmLabel={t("common.delete")}
        onConfirm={remove}
        onClose={() => setRemoving(null)}
      />
    </div>
  );
}
