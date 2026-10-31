"use client";

import { FileText, Loader2, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type FormEvent } from "react";

import { DueCell, StatusBadge } from "@/components/assignments/parts";
import { Button, ButtonLink } from "@/components/kit/button";
import { FormRow, Input, Segmented } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { EmptyState, ErrorState, NoResults } from "@/components/kit/states";
import { Skeleton } from "@/components/kit/skeleton";
import { Table, TBody, THead, Td, Th, Tr } from "@/components/kit/table";
import { useToast } from "@/components/kit/toast";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { MAX_TITLE_CHARS, dueFromInput, isWorking, workspaceError } from "@/lib/assignments";
import { relativeTime } from "@/lib/format";
import type { Assignment, AssignmentDetail } from "@/lib/types";

import type { Resource } from "./use-resource";

type Filter = "open" | "all" | "done";

/** The assignments that belong to this course, with a one-line way to add another. The
 *  workspace for each one (files, rubric, AI help, draft feedback, history) is its own page. */
export function AssignmentsTab({
  subjectId,
  assignments,
  onChanged,
}: {
  subjectId: string;
  assignments: Resource<Assignment[]>;
  onChanged: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const router = useRouter();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("open");
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);

  const items = assignments.data;
  const shown = useMemo(
    () => (items ?? []).filter((a) => (filter === "all" ? true : filter === "done" ? a.status === "done" : a.status !== "done")),
    [items, filter],
  );
  const openCount = (items ?? []).filter((a) => a.status !== "done").length;

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!title.trim() || busy) return;
    setBusy(true);
    try {
      const created = await api<AssignmentDetail>("/assignments", {
        method: "POST",
        body: { title: title.trim(), brief: "", subject_id: subjectId, due_at: dueFromInput(due) },
      });
      toast.success(t("asl.created"));
      onChanged();
      router.push(`/assignments/${created.id}`);
    } catch (caught) {
      toast.error(workspaceError(caught, t));
      setBusy(false);
    }
  }

  if (assignments.error && !items) return <ErrorState compact description={assignments.error} onRetry={assignments.reload} />;

  return (
    <div className="space-y-4">
      <form
        onSubmit={(event) => void create(event)}
        aria-label={t("assign.create.title")}
        className="grid gap-3 rounded-card border border-border bg-surface px-3.5 py-3 sm:grid-cols-[minmax(0,1fr)_9.5rem_auto] sm:items-end"
      >
        <FormRow label={t("assign.create.name")} htmlFor="course-assignment-title">
          <Input
            id="course-assignment-title"
            value={title}
            maxLength={MAX_TITLE_CHARS}
            placeholder={t("asl.create.placeholder")}
            onChange={(event) => setTitle(event.target.value)}
          />
        </FormRow>
        <FormRow label={`${t("assign.create.due")} (${t("common.optional")})`} htmlFor="course-assignment-due">
          <Input id="course-assignment-due" type="date" value={due} onChange={(event) => setDue(event.target.value)} />
        </FormRow>
        <Button type="submit" loading={busy} disabled={!title.trim()} title={!title.trim() ? t("asl.create.needTitle") : undefined}>
          <Plus className="h-4 w-4" aria-hidden />
          {t("assign.create.submit")}
        </Button>
      </form>

      <Panel
        id="course-assignments"
        title={t("sj.tab.assignments")}
        action={
          <Segmented
            label={t("sj.tab.assignments")}
            value={filter}
            onChange={setFilter}
            options={[
              { value: "open", label: t("sj.assignments.open"), count: items ? openCount : undefined },
              { value: "done", label: t("assign.status.done") },
              { value: "all", label: t("subjects.filterAll") },
            ]}
          />
        }
      >
        {assignments.loading || !items ? (
          <div className="space-y-3 p-3.5" aria-hidden>
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-4 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <EmptyState compact icon={FileText} title={t("sj.assignments.emptyTitle")} description={t("sj.assignments.emptyBody")}>
            <ButtonLink href="/assignments" variant="secondary" size="sm">
              {t("sj.assignments.openAll")}
            </ButtonLink>
          </EmptyState>
        ) : shown.length === 0 ? (
          <div className="px-4 py-6">
            <NoResults title={t("sj.assignments.noneInFilter")} />
          </div>
        ) : (
          <Table caption={t("sj.tab.assignments")}>
            <THead>
              <tr>
                <Th>{t("assign.create.name")}</Th>
                <Th>{t("assign.detail.status")}</Th>
                <Th>{t("asl.col.due")}</Th>
                <Th className="hidden lg:table-cell">{t("asl.col.work")}</Th>
                <Th className="hidden sm:table-cell" align="right">
                  {t("asl.col.activity")}
                </Th>
              </tr>
            </THead>
            <TBody>
              {shown.map((item) => (
                <Row key={item.id} item={item} locale={locale} />
              ))}
            </TBody>
          </Table>
        )}
      </Panel>
    </div>
  );
}

function Row({ item, locale }: { item: Assignment; locale: string }) {
  const t = useT();
  const working = item.runs.some((run) => isWorking(run.status));
  const ready = item.runs.filter((run) => run.status === "ready").length;
  const work: string[] = [];
  if (item.has_rubric) work.push(t("asl.work.rubric", { points: item.rubric_points }));
  work.push(item.word_count > 0 ? t("asl.work.draft", { words: item.word_count }) : t("asl.work.noDraft"));
  if (item.file_count > 0) work.push(t("asl.work.files", { count: item.file_count }));
  return (
    <Tr className={item.status === "done" ? "text-muted" : undefined}>
      <Td className="max-w-0 min-w-[10rem] sm:min-w-[14rem]">
        <Link href={`/assignments/${item.id}`} className="flex min-w-0 items-start gap-2 hover:text-brand">
          <FileText className="mt-0.5 h-4 w-4 shrink-0 text-faint" aria-hidden />
          <span className="block truncate font-medium" title={item.title}>
            {item.title}
          </span>
        </Link>
      </Td>
      <Td className="whitespace-nowrap">
        <StatusBadge status={item.status} />
      </Td>
      <Td className="whitespace-nowrap">
        <DueCell dueAt={item.due_at} status={item.status} locale={locale} />
      </Td>
      <Td className="hidden text-xs text-muted lg:table-cell">
        <span className="block">{work.join(" · ")}</span>
        {working ? (
          <span className="mt-0.5 flex items-center gap-1 text-info">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            {t("asl.work.running")}
          </span>
        ) : ready > 0 ? (
          <span className="mt-0.5 block">{t("asl.work.help", { count: ready })}</span>
        ) : null}
      </Td>
      <Td align="right" className="hidden whitespace-nowrap text-xs text-muted sm:table-cell">
        {item.last_activity_at ? relativeTime(item.last_activity_at, locale) : "—"}
      </Td>
    </Tr>
  );
}
