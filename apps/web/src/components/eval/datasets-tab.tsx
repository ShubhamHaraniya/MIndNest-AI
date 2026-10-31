"use client";

import { FileUp, ListChecks, Play, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { ConfirmDialog } from "@/components/kit/confirm";
import { EmptyState } from "@/components/kit/states";
import { Table, TBody, THead, Td, Th, Tr } from "@/components/kit/table";
import { useToast } from "@/components/kit/toast";
import { IconButton } from "@/components/subjects/bits";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { formatDate } from "@/components/groups/model";
import type { EvalDataset } from "@/lib/types";

/** The question sets: each is a list of questions with the passage that answers it. */
export function DatasetsTab({
  datasets,
  onImport,
  onRun,
  onChanged,
}: {
  datasets: EvalDataset[];
  onImport: () => void;
  onRun: (datasetId: string) => void;
  onChanged: () => Promise<void>;
}) {
  const t = useT();
  const locale = useLocale();
  const toast = useToast();
  const [removing, setRemoving] = useState<EvalDataset | null>(null);

  async function remove() {
    if (!removing) return;
    try {
      await api(`/eval/datasets/${removing.id}`, { method: "DELETE" });
      toast.success(t("evx.datasets.deleted", { name: removing.name }));
      await onChanged();
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  if (datasets.length === 0) {
    return (
      <EmptyState icon={ListChecks} title={t("evx.datasets.emptyTitle")} description={t("eval.datasets.empty")}>
        <Button onClick={onImport}>
          <FileUp className="h-4 w-4" aria-hidden />
          {t("eval.datasets.import")}
        </Button>
      </EmptyState>
    );
  }

  return (
    <div className="space-y-3">
      <p className="max-w-3xl text-[13px] text-muted">{t("eval.datasets.intro")}</p>
      <div className="rounded-card border border-border bg-surface">
        <Table caption={t("eval.datasets.title")}>
          <THead>
            <tr>
              <Th>{t("eval.import.name")}</Th>
              <Th className="hidden md:table-cell">{t("evx.col.searches")}</Th>
              <Th align="right">{t("evx.col.questions")}</Th>
              <Th className="hidden sm:table-cell">{t("evx.col.languages")}</Th>
              <Th className="hidden lg:table-cell">{t("evx.col.added")}</Th>
              <Th>
                <span className="sr-only">{t("evx.col.actions")}</span>
              </Th>
            </tr>
          </THead>
          <TBody>
            {datasets.map((dataset) => (
              <Tr key={dataset.id}>
                <Td className="max-w-[16rem]">
                  <Link href={`/eval/datasets/${dataset.id}`} className="block truncate font-medium text-brand hover:underline" title={dataset.name}>
                    {dataset.name}
                  </Link>
                </Td>
                <Td className="hidden text-muted md:table-cell">{dataset.subject_name ?? t("eval.import.allSubjects")}</Td>
                <Td align="right" className="tabular whitespace-nowrap">
                  {dataset.cases}
                  {dataset.unanswerable > 0 ? (
                    <Badge className="ml-2" title={t("eval.datasets.unanswerable", { count: dataset.unanswerable })}>
                      {t("evx.datasets.notIn", { count: dataset.unanswerable })}
                    </Badge>
                  ) : null}
                </Td>
                <Td className="hidden whitespace-nowrap text-muted sm:table-cell">
                  {Object.entries(dataset.languages)
                    .map(([code, count]) => `${t(`eval.lang.${code as "en" | "hi" | "gu"}`)} ${count}`)
                    .join(" · ")}
                </Td>
                <Td className="hidden whitespace-nowrap text-muted lg:table-cell">{formatDate(dataset.created_at, locale)}</Td>
                <Td align="right" className="whitespace-nowrap">
                  <span className="inline-flex items-center gap-1">
                    <Button variant="secondary" size="sm" onClick={() => onRun(dataset.id)}>
                      <Play className="h-3.5 w-3.5" aria-hidden />
                      {t("eval.datasets.run")}
                    </Button>
                    <IconButton label={`${t("common.delete")}: ${dataset.name}`} danger onClick={() => setRemoving(dataset)}>
                      <Trash2 className="h-3.5 w-3.5" aria-hidden />
                    </IconButton>
                  </span>
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      </div>

      <ConfirmDialog
        open={removing !== null}
        title={t("evx.datasets.deleteTitle")}
        description={t("eval.datasets.deleteConfirm", { name: removing?.name ?? "" })}
        confirmLabel={t("common.delete")}
        onConfirm={remove}
        onClose={() => setRemoving(null)}
      />
    </div>
  );
}
