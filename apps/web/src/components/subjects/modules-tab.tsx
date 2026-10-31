"use client";

import { FileUp, FolderOpen, Layers, Pencil, Tag, X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { ConfirmDialog } from "@/components/kit/confirm";
import { FormRow, Input } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { EmptyState, ErrorState } from "@/components/kit/states";
import { Skeleton } from "@/components/kit/skeleton";
import { Table, TBody, THead, Td, Th, Tr } from "@/components/kit/table";
import { useToast } from "@/components/kit/toast";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { relativeTime } from "@/lib/format";

import { AccuracyCell, IconButton } from "./bits";
import { TopicMap } from "./topic-map";
import { NO_MODULE, type CourseProgress, type ModuleProgress } from "./model";
import type { Resource } from "./use-resource";

const MAX_NAME = 80;

type Change = { module: ModuleProgress; mode: "rename" | "assign" } | { module: ModuleProgress; mode: "clear" };

/** The course by module: how many files, papers and notes each one holds and how well the
 *  student is doing on it. A module is a label on files, so it exists as long as a file carries it;
 *  renaming one relabels its files, and giving a name that already exists merges the two. */
export function ModulesTab({
  subjectId,
  courseName,
  progress,
  onOpenModule,
  onUpload,
  onChanged,
}: {
  subjectId: string;
  courseName: string;
  progress: Resource<CourseProgress>;
  /** Show this module's files in the Materials tab (NO_MODULE: files that are in no module). */
  onOpenModule: (module: string) => void;
  /** Upload files straight into a module ("" for a new one the dialog will ask for). */
  onUpload: (module: string) => void;
  onChanged: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const toast = useToast();
  const [change, setChange] = useState<Change | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const rows = progress.data?.modules ?? [];
  const named = new Set(rows.filter((r) => r.module !== null).map((r) => (r.module as string).toLocaleLowerCase()));

  function start(next: Change) {
    setChange(next);
    setName(next.mode === "rename" ? (next.module.module ?? "") : "");
    setFailure(null);
  }

  async function send(old: string | null, next: string | null): Promise<number> {
    const result = await api<{ updated: number }>(`/subjects/${subjectId}/modules/rename`, {
      method: "POST",
      body: { old, new: next },
    });
    onChanged();
    return result.updated;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!change || change.mode === "clear" || busy) return;
    const next = name.trim();
    if (!next) return;
    setBusy(true);
    setFailure(null);
    try {
      const merged = named.has(next.toLocaleLowerCase()) && next !== change.module.module;
      await send(change.module.module, next);
      toast.success(t(merged ? "sj.modules.merged" : "sj.modules.renamed", { name: next }));
      setChange(null);
    } catch (caught) {
      setFailure(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    if (!change || change.mode !== "clear" || change.module.module === null) return;
    try {
      await send(change.module.module, null);
      toast.success(t("sj.modules.cleared", { name: change.module.module }));
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  if (progress.error && !progress.data) return <ErrorState compact description={progress.error} onRetry={progress.reload} />;
  if (progress.loading || !progress.data) {
    return (
      <div className="space-y-3" aria-hidden>
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <EmptyState icon={Layers} title={t("sj.modules.emptyTitle")} description={t("sj.modules.emptyBody")}>
        <Button onClick={() => onUpload("")}>
          <FileUp className="h-4 w-4" aria-hidden />
          {t("sj.modules.uploadNew")}
        </Button>
      </EmptyState>
    );
  }

  const target = change?.module.module ?? null;

  return (
    <div className="space-y-4">
      <p className="max-w-2xl text-[13px] text-muted">{t("sj.modules.intro")}</p>

      <TopicMap courseName={courseName} modules={rows} onOpen={onOpenModule} />

      <Panel
        id="modules-table"
        title={t("sj.tab.modules")}
        action={
          <Button size="sm" onClick={() => onUpload("")}>
            <FileUp className="h-3.5 w-3.5" aria-hidden />
            {t("sj.modules.uploadNew")}
          </Button>
        }
      >
        <Table caption={t("sj.tab.modules")}>
          <THead>
            <tr>
              <Th className="w-full">{t("sj.col.module")}</Th>
              <Th align="right">{t("sj.col.ready")}</Th>
              <Th align="right" className="hidden sm:table-cell">
                {t("sj.tab.papers")}
              </Th>
              <Th align="right" className="hidden sm:table-cell">
                {t("sj.tab.notes")}
              </Th>
              <Th>{t("sj.col.accuracy")}</Th>
              <Th className="hidden lg:table-cell">{t("sj.col.practised")}</Th>
              <Th>
                <span className="sr-only">{t("sj.col.actions")}</span>
              </Th>
            </tr>
          </THead>
          <TBody>
            {rows.map((row) => {
              const label = row.module ?? t("sj.module.none");
              return (
                <Tr key={row.module ?? NO_MODULE}>
                  <Td className="max-w-0">
                    <button
                      type="button"
                      onClick={() => onOpenModule(row.module ?? NO_MODULE)}
                      className="flex w-full items-center gap-2 text-left font-medium hover:text-brand"
                      title={label}
                    >
                      <span className="truncate">
                        {row.module ?? <span className="font-normal text-muted">{label}</span>}
                      </span>
                      {row.weak ? <Badge tone="danger">{t("sj.progress.weak")}</Badge> : null}
                    </button>
                  </Td>
                  <Td align="right" className="tabular whitespace-nowrap">
                    {row.documents_ready}
                    <span className="text-faint"> / {row.documents}</span>
                  </Td>
                  <Td align="right" className="tabular hidden text-muted sm:table-cell">
                    {row.past_papers}
                  </Td>
                  <Td align="right" className="tabular hidden text-muted sm:table-cell">
                    {row.notes}
                  </Td>
                  <Td className="whitespace-nowrap">
                    <AccuracyCell
                      accuracy={row.accuracy}
                      answers={row.answers}
                      weak={row.weak}
                      label={t("sj.progress.accuracyOf", { name: label })}
                    />
                  </Td>
                  <Td className="hidden whitespace-nowrap text-muted lg:table-cell">
                    {row.last_practised_at ? relativeTime(row.last_practised_at, locale) : "—"}
                  </Td>
                  <Td align="right" className="whitespace-nowrap">
                    <span className="inline-flex items-center gap-0.5">
                      <IconButton label={t("sj.modules.openFiles", { name: label })} onClick={() => onOpenModule(row.module ?? NO_MODULE)}>
                        <FolderOpen className="h-3.5 w-3.5" aria-hidden />
                      </IconButton>
                      {row.module !== null ? (
                        <>
                          <IconButton label={t("sj.modules.uploadInto", { name: row.module })} onClick={() => onUpload(row.module as string)}>
                            <FileUp className="h-3.5 w-3.5" aria-hidden />
                          </IconButton>
                          <IconButton label={t("sj.modules.rename", { name: row.module })} onClick={() => start({ module: row, mode: "rename" })}>
                            <Pencil className="h-3.5 w-3.5" aria-hidden />
                          </IconButton>
                          <IconButton label={t("sj.modules.clear", { name: row.module })} danger onClick={() => start({ module: row, mode: "clear" })}>
                            <X className="h-3.5 w-3.5" aria-hidden />
                          </IconButton>
                        </>
                      ) : (
                        <IconButton label={t("sj.modules.assign")} onClick={() => start({ module: row, mode: "assign" })}>
                          <Tag className="h-3.5 w-3.5" aria-hidden />
                        </IconButton>
                      )}
                    </span>
                  </Td>
                </Tr>
              );
            })}
          </TBody>
        </Table>
      </Panel>

      <Dialog
        open={change !== null && change.mode !== "clear"}
        onClose={() => setChange(null)}
        title={change?.mode === "assign" ? t("sj.modules.assignTitle") : t("sj.modules.renameTitle", { name: target ?? "" })}
      >
        <form onSubmit={(event) => void submit(event)} className="space-y-4">
          {failure ? (
            <p role="alert" className="text-sm text-danger">
              {failure}
            </p>
          ) : null}
          <FormRow
            label={change?.mode === "assign" ? t("sj.modules.assignLabel", { count: change.module.documents }) : t("sj.modules.newName")}
            htmlFor="module-name"
            hint={t("sj.modules.mergeHint")}
          >
            <Input
              id="module-name"
              autoFocus
              value={name}
              maxLength={MAX_NAME}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("sj.modules.placeholder")}
            />
          </FormRow>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setChange(null)} disabled={busy}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" loading={busy} disabled={!name.trim() || name.trim() === target}>
              {t("common.save")}
            </Button>
          </div>
        </form>
      </Dialog>

      <ConfirmDialog
        open={change?.mode === "clear"}
        title={t("sj.modules.clearTitle", { name: target ?? "" })}
        description={t("sj.modules.clearBody", { count: change?.module.documents ?? 0 })}
        confirmLabel={t("sj.modules.clearConfirm")}
        tone="primary"
        onConfirm={clear}
        onClose={() => setChange(null)}
      />
    </div>
  );
}
