"use client";

import { ArrowRight, Check, Circle } from "lucide-react";
import { useState } from "react";

import { DueCell, StatusBadge } from "@/components/assignments/parts";
import { Select } from "@/components/kit/controls";
import { useToast } from "@/components/kit/toast";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { nextStep, readiness, workspaceError, type NextStep, type ReadinessKey } from "@/lib/assignments";
import { relativeTime } from "@/lib/format";
import type { AssignmentDetail, AssignmentStatus } from "@/lib/types";

export type WorkTab = "overview" | "files" | "instructions" | "rubric" | "help" | "feedback" | "history";

const STATUSES: AssignmentStatus[] = ["todo", "in_progress", "done"];

const GO: Record<ReadinessKey, WorkTab | "draft"> = {
  instructions: "instructions",
  files: "files",
  rubric: "rubric",
  draft: "draft",
  feedback: "feedback",
  version: "history",
};

/** Where this assignment stands: what has been set up, the one step worth doing next, and the
 *  latest help. Every figure comes from the assignment itself. */
export function OverviewTab({
  detail,
  onSaved,
  onGo,
}: {
  detail: AssignmentDetail;
  onSaved: (detail: AssignmentDetail) => void;
  /** Open a tab, or focus the draft editor. */
  onGo: (target: WorkTab | "draft") => void;
}) {
  const t = useT();
  const locale = useLocale();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const items = readiness(detail);
  const next = nextStep(items, detail.status);
  const lastRun = [...detail.latest_runs].filter((r) => r.status === "ready").sort((a, b) => b.created_at.localeCompare(a.created_at))[0];

  async function changeStatus(status: AssignmentStatus) {
    setBusy(true);
    try {
      onSaved(await api<AssignmentDetail>(`/assignments/${detail.id}`, { method: "PATCH", body: { status } }));
    } catch (caught) {
      toast.error(workspaceError(caught, t));
    } finally {
      setBusy(false);
    }
  }

  const target: Record<NextStep, WorkTab | "draft"> = {
    instructions: "instructions",
    draft: "draft",
    feedback: "feedback",
    version: "history",
    finish: "overview",
  };

  return (
    <div className="space-y-4 p-3.5">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-[13px]">
        <div>
          <dt className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{t("assign.detail.status")}</dt>
          <dd className="mt-1">
            <Select
              aria-label={t("assign.detail.status")}
              className="h-8 w-full"
              value={detail.status}
              disabled={busy}
              onChange={(event) => void changeStatus(event.target.value as AssignmentStatus)}
            >
              {STATUSES.map((value) => (
                <option key={value} value={value}>
                  {t(`assign.status.${value}`)}
                </option>
              ))}
            </Select>
          </dd>
        </div>
        <div>
          <dt className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{t("asl.col.due")}</dt>
          <dd className="mt-1.5">
            <DueCell dueAt={detail.due_at} status={detail.status} locale={locale} inline />
          </dd>
        </div>
        <div className="col-span-2">
          <dt className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{t("assign.create.subject")}</dt>
          <dd className="mt-1">{detail.subject_name ?? <span className="text-muted">{t("assign.create.anySubject")}</span>}</dd>
        </div>
      </dl>

      {detail.status === "done" ? (
        <p className="flex items-center gap-2 rounded-xl border border-border bg-surface-2 px-3 py-2.5 text-[13px]">
          <StatusBadge status="done" />
          {t("aw2.ov.done")}
        </p>
      ) : next ? (
        <button
          type="button"
          onClick={() => onGo(target[next])}
          className="flex w-full items-center gap-2 rounded-xl border border-primary/50 bg-primary-soft px-3.5 py-3 text-left transition-colors hover:border-primary"
        >
          <span className="min-w-0 flex-1">
            <span className="block text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{t("aw2.ov.next")}</span>
            <span className="block text-[13px] font-medium">{t(`aw2.ov.next.${next}`)}</span>
          </span>
          {next !== "finish" ? <ArrowRight className="h-4 w-4 shrink-0 text-brand rtl:rotate-180" aria-hidden /> : null}
        </button>
      ) : null}

      <section aria-label={t("aw2.ov.setup")}>
        <h3 className="mb-1.5 text-[13px] font-semibold">{t("aw2.ov.setup")}</h3>
        <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border">
          {items.map((item) => (
            <li key={item.key}>
              <button type="button" onClick={() => onGo(GO[item.key])} className="flex w-full items-center gap-2.5 px-2.5 py-2 text-left hover:bg-surface-2">
                {item.done ? (
                  <Check className="h-4 w-4 shrink-0 text-success" aria-hidden />
                ) : (
                  <Circle className="h-4 w-4 shrink-0 text-faint" aria-hidden />
                )}
                <span className="sr-only">{item.done ? t("aw2.ov.isDone") : t("aw2.ov.notYet")}:</span>
                <span className="min-w-0 flex-1 text-[13px]">{t(`aw2.ov.item.${item.key}`)}</span>
                <span className="tabular shrink-0 text-xs text-muted">{t(`aw2.ov.detail.${item.key}`, item.detail)}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <p className="text-xs text-muted">
        {lastRun
          ? t("aw2.ov.lastHelp", { kind: t(`assign.kind.${lastRun.kind}`), when: relativeTime(lastRun.finished_at ?? lastRun.created_at, locale) })
          : t("aw2.ov.noHelp")}
      </p>
    </div>
  );
}
