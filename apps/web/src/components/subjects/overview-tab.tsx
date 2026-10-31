"use client";

import { ChevronRight, FileText, FileUp } from "lucide-react";
import { useMemo } from "react";

import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { Panel, PanelLink } from "@/components/kit/panel";
import { ErrorState } from "@/components/kit/states";
import { Skeleton } from "@/components/kit/skeleton";
import { Table, TBody, THead, Td, Th, Tr } from "@/components/kit/table";
import { useLocale, useT } from "@/i18n/client";
import { formatDay, relativeTime } from "@/lib/format";
import type { Material } from "@/lib/types";

import { SyllabusRibbon } from "./syllabus";
import { AccuracyCell, dueText, dueTone } from "./bits";
import { KIND_KEYS, NO_MODULE, type CourseAnalytics, type CourseOverview, type CourseProgress } from "./model";
import { RecommendedNext } from "./recommended";
import type { Resource } from "./use-resource";

/** The course at a glance: its modules with readiness and accuracy, what was opened last, the
 *  exams ahead and the topics that need revision. Everything links to where it can be acted on. */
export function OverviewTab({
  subjectId,
  overview,
  progress,
  analytics,
  materials,
  onOpenModule,
  onOpenDoc,
  onShowProgress,
  onShowMaterials,
  onUpload,
}: {
  subjectId: string;
  overview: Resource<CourseOverview>;
  progress: Resource<CourseProgress>;
  analytics: Resource<CourseAnalytics>;
  materials: Resource<Material[]>;
  onOpenModule: (module: string | null) => void;
  onOpenDoc: (id: string) => void;
  onShowProgress: () => void;
  onShowMaterials: () => void;
  onUpload: () => void;
}) {
  const t = useT();
  const locale = useLocale();

  const recent = useMemo(
    () =>
      [...(materials.data ?? [])]
        .sort((a, b) => Date.parse(b.last_opened_at ?? b.created_at) - Date.parse(a.last_opened_at ?? a.created_at))
        .slice(0, 6),
    [materials.data],
  );
  const weak = useMemo(
    () =>
      (progress.data?.documents ?? [])
        .filter((doc) => doc.weak)
        .sort((a, b) => (a.accuracy ?? 1) - (b.accuracy ?? 1))
        .slice(0, 4),
    [progress.data],
  );

  const modules = progress.data?.modules ?? [];
  const namedModules = modules.filter((m) => m.module !== null).length;

  return (
    <div className="space-y-4">
      <RecommendedNext
        analytics={analytics}
        subjectId={subjectId}
        onOpenDoc={onOpenDoc}
        onUpload={onUpload}
        onShowMaterials={onShowMaterials}
      />

      <Panel
        id="modules"
        title={t("sj.overview.modules")}
        description={t("sj.overview.modulesHelp")}
        action={
          namedModules > 0 ? (
            <button type="button" onClick={() => onOpenModule("")} className="font-medium text-brand underline-offset-2 hover:underline">
              {t("sj.overview.allDocuments")}
            </button>
          ) : undefined
        }
      >
        {progress.error && !progress.data ? (
          <div className="p-3.5">
            <ErrorState compact description={progress.error} onRetry={progress.reload} />
          </div>
        ) : progress.loading ? (
          <div className="space-y-3 p-3.5" aria-hidden>
            {Array.from({ length: 3 }, (_, i) => (
              <Skeleton key={i} className="h-4 w-full" />
            ))}
          </div>
        ) : modules.length === 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-3 px-3.5 py-5">
            <p className="max-w-xl text-sm text-muted">{t("sj.overview.noModules")}</p>
            <Button size="sm" variant="secondary" onClick={onUpload}>
              <FileUp className="h-3.5 w-3.5" aria-hidden />
              {t("sj.upload.button")}
            </Button>
          </div>
        ) : (
          <>
            <SyllabusRibbon modules={modules} onOpen={onOpenModule} />
            <Table caption={t("sj.overview.modules")}>
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
                  <Th align="right" className="hidden md:table-cell">
                    {t("sj.col.answers")}
                  </Th>
                  <Th className="hidden lg:table-cell">{t("sj.col.practised")}</Th>
                  <Th>
                    <span className="sr-only">{t("sj.col.actions")}</span>
                  </Th>
                </tr>
              </THead>
              <TBody>
                {modules.map((row) => (
                  <Tr key={row.module ?? NO_MODULE} className="cursor-pointer" onClick={() => onOpenModule(row.module ?? NO_MODULE)}>
                    <Td className="max-w-0">
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          onOpenModule(row.module ?? NO_MODULE);
                        }}
                        className="block w-full truncate text-left font-medium hover:text-brand"
                        title={row.module ?? t("sj.module.none")}
                      >
                        {row.module ?? <span className="font-normal text-muted">{t("sj.module.none")}</span>}
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
                        label={t("sj.progress.accuracyOf", { name: row.module ?? t("sj.module.none") })}
                      />
                    </Td>
                    <Td align="right" className="tabular hidden text-muted md:table-cell">
                      {row.answers || "—"}
                    </Td>
                    <Td className="hidden whitespace-nowrap text-muted lg:table-cell">
                      {row.last_practised_at ? relativeTime(row.last_practised_at, locale) : "—"}
                    </Td>
                    <Td align="right">
                      <ChevronRight className="h-3.5 w-3.5 text-faint rtl:rotate-180" aria-hidden />
                    </Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
            {namedModules === 0 ? (
              <p className="border-t border-border px-3.5 py-2 text-xs text-muted">{t("sj.overview.noModules")}</p>
            ) : null}
          </>
        )}
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel id="recent" title={t("wb.docs.title")}>
          {materials.loading ? (
            <div className="space-y-3 p-3.5" aria-hidden>
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ) : recent.length === 0 ? (
            <p className="px-3.5 py-4 text-sm text-muted">{t("wb.docs.empty")}</p>
          ) : (
            <ul className="divide-y divide-border">
              {recent.map((doc) => (
                <li key={doc.id}>
                  <button
                    type="button"
                    onClick={() => onOpenDoc(doc.id)}
                    className="flex w-full items-center gap-2.5 px-3.5 py-2 text-left hover:bg-surface-2"
                  >
                    <FileText className="h-4 w-4 shrink-0 text-faint" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-medium">{doc.filename}</span>
                      <span className="block truncate text-xs text-muted">
                        {[t(KIND_KEYS[doc.kind]), doc.module].filter(Boolean).join(" · ")}
                      </span>
                    </span>
                    <span className="shrink-0 text-xs text-muted">
                      {t(doc.last_opened_at ? "wb.docs.opened" : "wb.docs.added", {
                        when: relativeTime(doc.last_opened_at ?? doc.created_at, locale),
                      })}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="min-w-0 space-y-4">
          <Panel id="exams" title={t("sj.overview.exams")} action={<PanelLink href="/planner">{t("wb.today.openPlanner")}</PanelLink>}>
            {overview.loading ? (
              <div className="p-3.5" aria-hidden>
                <Skeleton className="h-4 w-2/3" />
              </div>
            ) : (overview.data?.exams ?? []).length === 0 ? (
              <p className="px-3.5 py-4 text-sm text-muted">{t("sj.overview.noExams")}</p>
            ) : (
              <ul className="divide-y divide-border">
                {overview.data?.exams.map((exam) => (
                  <li key={exam.id} className="flex items-center gap-3 px-3.5 py-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-medium">{exam.title}</p>
                      <p className="text-xs text-muted">{formatDay(exam.exam_on, locale, { weekday: "short", day: "numeric", month: "short" })}</p>
                    </div>
                    <Badge tone={dueTone(exam.days_left)}>{dueText(t, exam.days_left)}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel
            id="revise"
            title={t("wb.weak.title")}
            action={
              <button type="button" onClick={onShowProgress} className="font-medium text-brand underline-offset-2 hover:underline">
                {t("sj.overview.allProgress")}
              </button>
            }
          >
            {progress.loading ? (
              <div className="p-3.5" aria-hidden>
                <Skeleton className="h-4 w-2/3" />
              </div>
            ) : weak.length === 0 ? (
              <p className="px-3.5 py-4 text-sm text-muted">
                {(progress.data?.summary.answers ?? 0) > 0 ? t("sj.overview.nothingWeak") : t("wb.weak.empty")}
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {weak.map((doc) => (
                  <li key={doc.filename} className="flex items-center gap-3 px-3.5 py-2">
                    <div className="min-w-0 flex-1">
                      {doc.material_id ? (
                        <button type="button" onClick={() => onOpenDoc(doc.material_id as string)} className="block max-w-full truncate text-left text-[13px] font-medium hover:text-brand">
                          {doc.filename}
                        </button>
                      ) : (
                        <p className="truncate text-[13px] font-medium">{doc.filename}</p>
                      )}
                      {doc.module ? <p className="truncate text-xs text-muted">{doc.module}</p> : null}
                    </div>
                    <AccuracyCell accuracy={doc.accuracy} answers={doc.answers} weak label={t("sj.progress.accuracyOf", { name: doc.filename })} />
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
