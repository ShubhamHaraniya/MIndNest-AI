"use client";

import { ListChecks, MessageSquare } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge } from "@/components/kit/badge";
import { ButtonLink } from "@/components/kit/button";
import { Segmented } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { EmptyState, ErrorState, NoResults } from "@/components/kit/states";
import { Skeleton } from "@/components/kit/skeleton";
import { Table, TBody, THead, Td, Th, Tr } from "@/components/kit/table";
import { useLocale, useT } from "@/i18n/client";
import { percent, relativeTime } from "@/lib/format";

import { AccuracyCell, IconButton, microLabel } from "./bits";
import { NO_MODULE, type CourseProgress } from "./model";
import type { Resource } from "./use-resource";

type Filter = "all" | "weak" | "practised";

/** Topic progress: how the student is doing on each source document and each module, taken from
 *  the marked answers of this course's quizzes. A document under 80% over three or more answers
 *  is flagged for revision (the same rule the dashboard uses). */
export function ProgressTab({
  progress,
  subjectId,
  onOpenDoc,
  onOpenModule,
  onAsk,
}: {
  progress: Resource<CourseProgress>;
  subjectId: string;
  onOpenDoc: (id: string) => void;
  onOpenModule: (module: string) => void;
  onAsk: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const [filter, setFilter] = useState<Filter>("all");
  const data = progress.data;

  const documents = useMemo(() => {
    const list = (data?.documents ?? []).filter((doc) => (filter === "weak" ? doc.weak : filter === "practised" ? doc.answers > 0 : true));
    // Weakest first, then the ones never practised, then the strong ones.
    const rank = (accuracy: number | null, weak: boolean) => (weak ? 0 : accuracy === null ? 1 : 2);
    return [...list].sort(
      (a, b) =>
        rank(a.accuracy, a.weak) - rank(b.accuracy, b.weak) ||
        (a.accuracy ?? 1) - (b.accuracy ?? 1) ||
        a.filename.localeCompare(b.filename),
    );
  }, [data, filter]);

  if (progress.error && !data) return <ErrorState compact description={progress.error} onRetry={progress.reload} />;
  if (progress.loading || !data) {
    return (
      <div className="space-y-4" aria-hidden>
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const { summary } = data;
  if (data.documents.length === 0 && summary.answers === 0) {
    return (
      <EmptyState icon={ListChecks} title={t("sj.progress.emptyTitle")} description={t("sj.progress.emptyBody")}>
        <ButtonLink href="/quizzes">{t("nav.quizzes")}</ButtonLink>
      </EmptyState>
    );
  }

  const facts = [
    { label: t("sj.progress.factAnswers"), value: String(summary.answers) },
    { label: t("sj.progress.factAccuracy"), value: percent(summary.accuracy) },
    { label: t("sj.progress.factAttempts"), value: String(summary.attempts) },
    { label: t("sj.progress.factWeak"), value: String(summary.weak_documents), warn: summary.weak_documents > 0 },
    { label: t("sj.col.practised"), value: summary.last_practised_at ? relativeTime(summary.last_practised_at, locale) : "—" },
  ];

  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 divide-x divide-y divide-border rounded-card border border-border bg-surface sm:grid-cols-3 sm:divide-y-0 lg:grid-cols-5">
        {facts.map((fact) => (
          <div key={fact.label} className="min-w-0 px-3.5 py-2">
            <dt className={microLabel()}>{fact.label}</dt>
            <dd className={`tabular truncate text-[13px] ${fact.warn ? "font-medium text-danger" : ""}`}>{fact.value}</dd>
          </div>
        ))}
      </dl>

      {data.modules.some((m) => m.module !== null) ? (
        <Panel id="module-progress" title={t("sj.progress.byModule")} description={t("sj.progress.byModuleHelp")}>
          <Table caption={t("sj.progress.byModule")}>
            <THead>
              <tr>
                <Th className="w-full">{t("sj.col.module")}</Th>
                <Th align="right" className="hidden sm:table-cell">
                  {t("sj.col.documents")}
                </Th>
                <Th align="right" className="hidden sm:table-cell">
                  {t("sj.col.answers")}
                </Th>
                <Th>{t("sj.col.accuracy")}</Th>
                <Th className="hidden md:table-cell">{t("sj.col.practised")}</Th>
                <Th>
                  <span className="sr-only">{t("sj.col.actions")}</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {data.modules.map((row) => (
                <Tr key={row.module ?? NO_MODULE}>
                  <Td className="max-w-0">
                    <button
                      type="button"
                      onClick={() => onOpenModule(row.module ?? NO_MODULE)}
                      className="block w-full truncate text-left font-medium hover:text-brand"
                      title={row.module ?? t("sj.module.none")}
                    >
                      {row.module ?? <span className="font-normal text-muted">{t("sj.module.none")}</span>}
                    </button>
                  </Td>
                  <Td align="right" className="tabular hidden text-muted sm:table-cell">
                    {row.documents}
                  </Td>
                  <Td align="right" className="tabular hidden text-muted sm:table-cell">
                    {row.answers || "—"}
                  </Td>
                  <Td className="whitespace-nowrap">
                    <AccuracyCell
                      accuracy={row.accuracy}
                      answers={row.answers}
                      weak={row.weak}
                      label={t("sj.progress.accuracyOf", { name: row.module ?? t("sj.module.none") })}
                    />
                  </Td>
                  <Td className="hidden whitespace-nowrap text-muted md:table-cell">
                    {row.last_practised_at ? relativeTime(row.last_practised_at, locale) : "—"}
                  </Td>
                  <Td align="right" className="whitespace-nowrap">
                    {row.weak ? <Badge tone="danger">{t("sj.progress.weak")}</Badge> : null}
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </Panel>
      ) : null}

      <Panel
        id="document-progress"
        title={t("sj.progress.byDocument")}
        description={t("sj.progress.byDocumentHelp")}
        action={
          <Segmented
            label={t("sj.progress.byDocument")}
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: t("subjects.filterAll") },
              { value: "weak", label: t("sj.progress.weak"), count: summary.weak_documents },
              { value: "practised", label: t("sj.progress.practised") },
            ]}
          />
        }
      >
        {documents.length === 0 ? (
          <div className="px-4 py-6">
            <NoResults title={t("sj.progress.noneInFilter")} />
          </div>
        ) : (
          <Table caption={t("sj.progress.byDocument")}>
            <THead>
              <tr>
                <Th className="w-full">{t("sj.col.name")}</Th>
                <Th className="hidden md:table-cell">{t("sj.col.module")}</Th>
                <Th align="right" className="hidden sm:table-cell">
                  {t("sj.col.answers")}
                </Th>
                <Th>{t("sj.col.accuracy")}</Th>
                <Th className="hidden lg:table-cell">{t("sj.col.practised")}</Th>
                <Th>
                  <span className="sr-only">{t("sj.col.actions")}</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {documents.map((doc) => (
                <Tr key={`${doc.material_id ?? "gone"}-${doc.filename}`}>
                  <Td className="max-w-0">
                    {doc.material_id ? (
                      <button
                        type="button"
                        onClick={() => onOpenDoc(doc.material_id as string)}
                        className="block w-full truncate text-left font-medium hover:text-brand"
                        title={doc.filename}
                      >
                        {doc.filename}
                      </button>
                    ) : (
                      <span className="flex items-center gap-2">
                        <span className="truncate font-medium" title={doc.filename}>
                          {doc.filename}
                        </span>
                        <Badge>{t("sj.progress.deleted")}</Badge>
                      </span>
                    )}
                  </Td>
                  <Td className="hidden max-w-[11rem] truncate text-muted md:table-cell">{doc.module ?? <span className="text-faint">{t("sj.module.none")}</span>}</Td>
                  <Td align="right" className="tabular hidden text-muted sm:table-cell">
                    {doc.answers || "—"}
                  </Td>
                  <Td className="whitespace-nowrap">
                    <span className="flex items-center gap-2">
                      <AccuracyCell
                        accuracy={doc.accuracy}
                        answers={doc.answers}
                        weak={doc.weak}
                        label={t("sj.progress.accuracyOf", { name: doc.filename })}
                      />
                      {doc.weak ? <Badge tone="danger">{t("sj.progress.weak")}</Badge> : null}
                    </span>
                  </Td>
                  <Td className="hidden whitespace-nowrap text-muted lg:table-cell">
                    {doc.last_practised_at ? relativeTime(doc.last_practised_at, locale) : "—"}
                  </Td>
                  <Td align="right" className="whitespace-nowrap">
                    <span className="inline-flex items-center gap-0.5">
                      <Link
                        href={`/quizzes?subject=${subjectId}`}
                        aria-label={t("sj.progress.practise")}
                        title={t("sj.progress.practise")}
                        className="inline-flex h-7 w-7 items-center justify-center rounded text-muted hover:bg-surface-3 hover:text-ink"
                      >
                        <ListChecks className="h-3.5 w-3.5" aria-hidden />
                      </Link>
                      <IconButton label={t("sj.action.askAbout")} onClick={onAsk}>
                        <MessageSquare className="h-3.5 w-3.5" aria-hidden />
                      </IconButton>
                    </span>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Panel>
    </div>
  );
}
