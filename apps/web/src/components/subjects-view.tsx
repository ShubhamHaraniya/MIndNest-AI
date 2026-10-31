"use client";

import { Stagger, StaggerItem } from "@/components/motion/reveal";
import { Archive, ArchiveRestore, BookOpen, Crosshair, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { Segmented, SearchField } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { EmptyState, ErrorState, NoResults } from "@/components/kit/states";
import { Skeleton } from "@/components/kit/skeleton";
import { Table, TBody, THead, Td, Th, Tr } from "@/components/kit/table";
import { useToast } from "@/components/kit/toast";
import { setCourseCookie } from "@/components/shell/course";
import { IconButton, dueText, dueTone } from "@/components/subjects/bits";
import { CourseCard } from "@/components/subjects/course-card";
import { CourseFormDialog, DeleteCourseDialog, type CourseDraft } from "@/components/subjects/course-dialogs";
import type { CourseFigures, CoursePage } from "@/components/subjects/model";
import { useResource } from "@/components/subjects/use-resource";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { percent, relativeTime } from "@/lib/format";

type StateFilter = "active" | "archived" | "all";
type View = "cards" | "table";
const VIEW_KEY = "mindnest.courses.view";

/** The student's courses as one table: what is in each, how practice is going, the next exam, and
 *  the actions on the course. A row opens the course workspace. */
export function SubjectsView({ openNewOnLoad = false, currentId }: { openNewOnLoad?: boolean; currentId: string | null }) {
  const t = useT();
  const locale = useLocale();
  const router = useRouter();
  const toast = useToast();

  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<StateFilter>("active");
  const [view, setView] = useState<View>("cards");
  const [formOpen, setFormOpen] = useState(openNewOnLoad);
  const [editing, setEditing] = useState<CourseDraft | null>(null);
  const [deleting, setDeleting] = useState<CourseFigures | null>(null);

  // Remember the chosen layout on this device (a convenience only; the page works without it).
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(VIEW_KEY);
      if (saved === "cards" || saved === "table") setView(saved);
    } catch {
      // storage unavailable
    }
  }, []);

  function chooseView(next: View) {
    setView(next);
    try {
      window.localStorage.setItem(VIEW_KEY, next);
    } catch {
      // storage unavailable
    }
  }

  // Wait for a pause in typing before querying.
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const params = new URLSearchParams({ state: filter });
  if (query) params.set("q", query);
  const courses = useResource<CoursePage>(`/courses?${params.toString()}`, { keepPrevious: true });
  const items = courses.data?.items ?? [];

  function makeCurrent(course: CourseFigures) {
    setCourseCookie(course.id);
    router.refresh();
    toast.success(t("sj.list.nowCurrent", { name: course.name }));
  }

  async function toggleArchive(course: CourseFigures) {
    try {
      await api(`/subjects/${course.id}/${course.archived_at ? "unarchive" : "archive"}`, { method: "POST" });
      courses.reload();
      router.refresh(); // the sidebar's course list
      toast.success(t(course.archived_at ? "sj.list.restored" : "sj.list.archived", { name: course.name }));
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  const filtering = query !== "" || filter !== "active";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <SearchField value={search} onChange={setSearch} placeholder={t("subjects.search")} className="w-full sm:w-72" />
        <Segmented
          label={t("subjects.title")}
          value={filter}
          onChange={setFilter}
          options={[
            { value: "active", label: t("subjects.filterActive") },
            { value: "archived", label: t("subjects.filterArchived") },
            { value: "all", label: t("subjects.filterAll") },
          ]}
        />
        <Segmented
          label={t("sj.view.label")}
          value={view}
          onChange={chooseView}
          options={[
            { value: "cards", label: t("sj.view.cards") },
            { value: "table", label: t("sj.view.table") },
          ]}
        />
        <Button
          className="ml-auto"
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
        >
          <Plus className="h-4 w-4" aria-hidden />
          {t("subjects.new")}
        </Button>
      </div>

      {courses.error && !courses.data ? (
        <ErrorState description={courses.error} onRetry={courses.reload} />
      ) : courses.loading && view === "cards" ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-hidden>
          {Array.from({ length: 3 }, (_, index) => (
            <Skeleton key={index} className="h-60 w-full rounded-card" />
          ))}
        </div>
      ) : courses.loading ? (
        <Panel id="courses" title={t("sj.list.title")}>
          <div className="space-y-4 p-3.5" aria-hidden>
            {Array.from({ length: 3 }, (_, index) => (
              <div key={index} className="flex gap-4">
                <Skeleton className="h-4 w-1/3" />
                <Skeleton className="h-4 flex-1" />
              </div>
            ))}
          </div>
        </Panel>
      ) : items.length === 0 ? (
        filtering ? (
          <NoResults title={t("subjects.noResults")} description={t("sj.list.noResultsHelp")}>
            <Button
              variant="secondary"
              onClick={() => {
                setSearch("");
                setFilter("active");
              }}
            >
              {t("sj.filter.clear")}
            </Button>
          </NoResults>
        ) : (
          <EmptyState icon={BookOpen} title={t("sj.list.emptyTitle")} description={t("sj.list.emptyBody")}>
            <Button onClick={() => setFormOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden />
              {t("sj.list.createFirst")}
            </Button>
          </EmptyState>
        )
      ) : view === "cards" ? (
        <Stagger as="ul" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((course) => (
            <StaggerItem as="li" key={course.id} className="flex [&>*]:w-full">
                <CourseCard
                  course={course}
                  current={course.id === currentId}
                  onMakeCurrent={() => makeCurrent(course)}
                  onEdit={() => {
                    setEditing(course);
                    setFormOpen(true);
                  }}
                  onArchive={() => void toggleArchive(course)}
                  onDelete={() => setDeleting(course)}
                />
            </StaggerItem>
          ))}
        </Stagger>
      ) : (
        <Panel id="courses" title={t("subjects.total", { count: items.length })}>
          <Table caption={t("subjects.title")}>
            <THead>
              <tr>
                <Th className="w-full min-w-[11rem]">{t("sj.col.course")}</Th>
                <Th className="hidden md:table-cell">{t("sj.col.code")}</Th>
                <Th className="hidden lg:table-cell">{t("subjects.fieldSemester")}</Th>
                <Th align="right">{t("sj.col.documents")}</Th>
                <Th align="right" className="hidden lg:table-cell">
                  {t("sj.tab.papers")}
                </Th>
                <Th align="right" className="hidden lg:table-cell">
                  {t("sj.tab.notes")}
                </Th>
                <Th align="right" className="hidden sm:table-cell">
                  {t("sj.col.quizAverage")}
                </Th>
                <Th className="hidden md:table-cell">{t("wb.course.exam")}</Th>
                <Th className="hidden xl:table-cell">{t("sj.col.lastActivity")}</Th>
                <Th>
                  <span className="sr-only">{t("sj.col.actions")}</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {items.map((course) => {
                const current = course.id === currentId;
                return (
                  <Tr
                    key={course.id}
                    className="cursor-pointer"
                    onClick={(event) => {
                      if ((event.target as HTMLElement).closest("a,button")) return;
                      router.push(`/subjects/${course.id}`);
                    }}
                  >
                    <Td className="max-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <Link href={`/subjects/${course.id}`} className="truncate font-medium hover:text-brand" title={course.name}>
                          {course.name}
                        </Link>
                        {current ? <Badge tone="brand">{t("sj.list.current")}</Badge> : null}
                        {course.archived_at ? <Badge>{t("subjects.archivedBadge")}</Badge> : null}
                      </div>
                      <p className="truncate text-xs text-muted md:hidden">
                        {[course.course_code, course.semester].filter(Boolean).join(" · ") || t("sj.list.noCode")}
                      </p>
                      {course.description ? (
                        <p className="hidden truncate text-xs text-muted md:block" title={course.description}>
                          {course.description}
                        </p>
                      ) : null}
                    </Td>
                    <Td className="hidden whitespace-nowrap text-muted md:table-cell">{course.course_code ?? "—"}</Td>
                    <Td className="hidden max-w-[9rem] truncate text-muted lg:table-cell">{course.semester ?? "—"}</Td>
                    <Td align="right" className="whitespace-nowrap">
                      <span className="tabular" title={t("sj.list.readyOf", { ready: course.documents_ready, total: course.documents })}>
                        {course.documents_ready}
                        <span className="text-faint"> / {course.documents}</span>
                      </span>
                      {course.documents_failed > 0 ? (
                        <Badge tone="danger" className="ml-1.5">
                          {t("sj.list.failed", { count: course.documents_failed })}
                        </Badge>
                      ) : course.documents_working > 0 ? (
                        <Badge tone="info" className="ml-1.5">
                          {t("sj.list.reading", { count: course.documents_working })}
                        </Badge>
                      ) : null}
                    </Td>
                    <Td align="right" className="tabular hidden text-muted lg:table-cell">
                      {course.past_papers}
                    </Td>
                    <Td align="right" className="tabular hidden text-muted lg:table-cell">
                      {course.notes}
                    </Td>
                    <Td align="right" className="hidden whitespace-nowrap sm:table-cell">
                      {course.quiz_attempts > 0 ? (
                        <span className="tabular" title={t("sj.list.attempts", { count: course.quiz_attempts })}>
                          {percent(course.quiz_average)}
                          <span className="ml-1 text-xs text-faint">· {course.quiz_attempts}</span>
                        </span>
                      ) : (
                        <span className="text-faint">—</span>
                      )}
                    </Td>
                    <Td className="hidden max-w-[12rem] md:table-cell">
                      {course.next_exam_title && course.next_exam_days !== null ? (
                        <div className="flex min-w-0 items-center gap-1.5">
                          <span className="truncate" title={course.next_exam_title}>
                            {course.next_exam_title}
                          </span>
                          <Badge tone={dueTone(course.next_exam_days)} className="shrink-0">
                            {dueText(t, course.next_exam_days)}
                          </Badge>
                        </div>
                      ) : (
                        <span className="text-faint">{t("wb.course.noExam")}</span>
                      )}
                    </Td>
                    <Td className="hidden whitespace-nowrap text-muted xl:table-cell">
                      {course.last_activity_at ? relativeTime(course.last_activity_at, locale) : "—"}
                    </Td>
                    <Td align="right" className="whitespace-nowrap">
                      <span className="inline-flex items-center justify-end gap-0.5">
                        {!course.archived_at && !current ? (
                          <IconButton label={t("sj.list.makeCurrent")} onClick={() => makeCurrent(course)}>
                            <Crosshair className="h-3.5 w-3.5" aria-hidden />
                          </IconButton>
                        ) : null}
                        <IconButton
                          label={t("common.edit")}
                          onClick={() => {
                            setEditing(course);
                            setFormOpen(true);
                          }}
                        >
                          <Pencil className="h-3.5 w-3.5" aria-hidden />
                        </IconButton>
                        <IconButton
                          label={course.archived_at ? t("subjects.unarchive") : t("subjects.archive")}
                          onClick={() => void toggleArchive(course)}
                        >
                          {course.archived_at ? <ArchiveRestore className="h-3.5 w-3.5" aria-hidden /> : <Archive className="h-3.5 w-3.5" aria-hidden />}
                        </IconButton>
                        <IconButton label={t("common.delete")} danger onClick={() => setDeleting(course)}>
                          <Trash2 className="h-3.5 w-3.5" aria-hidden />
                        </IconButton>
                      </span>
                    </Td>
                  </Tr>
                );
              })}
            </TBody>
          </Table>
        </Panel>
      )}

      <CourseFormDialog
        open={formOpen}
        course={editing}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        onSaved={(saved, created) => {
          setFormOpen(false);
          setEditing(null);
          courses.reload();
          toast.success(t(created ? "sj.list.created" : "sj.list.saved", { name: saved.name }));
          if (created) router.refresh(); // the sidebar's course list
        }}
      />
      <DeleteCourseDialog
        course={deleting}
        onClose={() => setDeleting(null)}
        onDeleted={(id) => {
          const name = deleting?.name ?? "";
          setDeleting(null);
          if (id === currentId) setCourseCookie(null);
          courses.reload();
          router.refresh();
          toast.success(t("sj.list.deleted", { name }));
        }}
      />
    </div>
  );
}
