"use client";

import { ArrowRight, Plus, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/kit/button";
import { ConfirmDialog } from "@/components/kit/confirm";
import { SearchField, Select } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { Skeleton } from "@/components/kit/skeleton";
import { EmptyState, ErrorState, NoResults } from "@/components/kit/states";
import { useToast } from "@/components/kit/toast";
import { PageHeader } from "@/components/page";
import { CreateQuizDialog } from "@/components/quizzes/create-dialog";
import { QuizTable } from "@/components/quizzes/quiz-table";
import { HubSidebar } from "@/components/quizzes/hub-sidebar";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { beginAttempt, isWriting, quizError } from "@/lib/quiz";
import type { Quiz, QuizProgress, Subject } from "@/lib/types";

const POLL_MS = 3000;
type StatusFilter = "all" | "ready" | "in_progress" | "completed" | "archived" | "writing" | "failed";

export function QuizHub({ subjects, initialCourse }: { subjects: Subject[]; initialCourse: string | null }) {
  const t = useT();
  const router = useRouter();
  const toast = useToast();
  const [quizzes, setQuizzes] = useState<Quiz[] | null>(null);
  const [progress, setProgress] = useState<QuizProgress | null>(null);
  const [failed, setFailed] = useState(false);
  const [creating, setCreating] = useState(false);
  const [toDelete, setToDelete] = useState<Quiz | null>(null);
  const [toArchive, setToArchive] = useState<Quiz | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [course, setCourse] = useState(initialCourse ?? "");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [openOnly, setOpenOnly] = useState(false);

  const load = useCallback(async () => {
    try {
      const [loadedQuizzes, loadedProgress] = await Promise.all([api<Quiz[]>("/quizzes"), api<QuizProgress>("/progress")]);
      setQuizzes(loadedQuizzes);
      setProgress(loadedProgress);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const anyWriting = quizzes?.some((quiz) => isWriting(quiz.status)) ?? false;
  useEffect(() => {
    if (!anyWriting) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [anyWriting, load]);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (quizzes ?? []).filter((quiz) => {
      if (needle && !`${quiz.title} ${quiz.subject_name ?? ""}`.toLowerCase().includes(needle)) return false;
      if (course && quiz.subject_id !== course) return false;
      // "All active" hides archived quizzes; they are listed under their own filter.
      if (status === "all") {
        if (quiz.display_status === "archived") return false;
      } else if (status === "writing") {
        if (!isWriting(quiz.status) || quiz.display_status === "archived") return false;
      } else if (quiz.display_status !== status) return false;
      if (openOnly && !quiz.open_attempt_id) return false;
      return true;
    });
  }, [quizzes, query, course, status, openOnly]);

  const filtering = query.trim() !== "" || course !== "" || status !== "all" || openOnly;
  const openCount = quizzes?.filter((quiz) => quiz.open_attempt_id && quiz.display_status !== "archived").length ?? 0;
  const archivedCount = quizzes?.filter((quiz) => quiz.display_status === "archived").length ?? 0;

  // The quiz to offer first: one the student has started and not finished.
  const resume = useMemo(
    () => (quizzes ?? []).find((quiz) => quiz.open_attempt_id && quiz.display_status !== "archived") ?? null,
    [quizzes],
  );

  const dueBySubject = useMemo(() => {
    const due: Record<string, number> = { "": progress?.revision.due ?? 0 };
    for (const row of progress?.revision.due_by_subject ?? []) if (row.subject_id) due[row.subject_id] = row.due;
    return due;
  }, [progress]);

  async function start(quiz: Quiz) {
    setBusyId(quiz.id);
    try {
      router.push(`/quizzes/attempt/${quiz.open_attempt_id ?? (await beginAttempt(quiz.id))}`);
    } catch (caught) {
      toast.error(quizError(caught, t));
      setBusyId(null);
    }
  }

  async function retry(quiz: Quiz) {
    setBusyId(quiz.id);
    try {
      await api<Quiz>(`/quizzes/${quiz.id}/retry`, { method: "POST" });
      toast.info(t("qz.retrying"));
      await load();
    } catch (caught) {
      toast.error(quizError(caught, t));
    } finally {
      setBusyId(null);
    }
  }

  async function remove() {
    if (!toDelete) return;
    try {
      await api(`/quizzes/${toDelete.id}`, { method: "DELETE" });
      toast.success(t("qz.deleted"));
      await load();
    } catch (caught) {
      toast.error(quizError(caught, t));
    }
  }

  async function setArchived(quiz: Quiz, archived: boolean) {
    setBusyId(quiz.id);
    try {
      await api<Quiz>(`/quizzes/${quiz.id}`, { method: "PATCH", body: { archived } });
      toast.success(archived ? t("qzx.archived") : t("qzx.restored"));
      await load();
    } catch (caught) {
      toast.error(quizError(caught, t));
    } finally {
      setBusyId(null);
    }
  }

  function clearFilters() {
    setQuery("");
    setCourse("");
    setStatus("all");
    setOpenOnly(false);
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("nav.quizzes")}
        description={t("navdesc.quizzes")}
        help="quizzes"
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            {t("quiz.create.button")}
          </Button>
        }
      />

      {resume ? (
        <section
          aria-label={t("qz2.resume.label")}
          className="glass sheen flex flex-wrap items-center gap-4 rounded-3xl p-5"
        >
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-brand">
            <Play className="h-5 w-5" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-brand rtl:tracking-normal">{t("qz2.resume.label")}</p>
            <p className="truncate text-base font-semibold" title={resume.title}>
              {resume.title}
            </p>
            {resume.subject_name ? <p className="truncate text-xs text-muted">{resume.subject_name}</p> : null}
          </div>
          <Button size="lg" loading={busyId === resume.id} onClick={() => void start(resume)}>
            {t("qz2.resume.cta")}
            <ArrowRight className="h-4 w-4 rtl:rotate-180" aria-hidden />
          </Button>
        </section>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_21rem] xl:grid-cols-[minmax(0,1fr)_23rem]">
        <Panel
          id="quizzes"
          title={t("quiz.list.title")}
          description={quizzes ? t("qz.hub.count", { shown: shown.length, total: quizzes.length }) : undefined}
          className="min-w-0"
        >
          {quizzes && quizzes.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2 border-b border-border px-3.5 py-2">
              <SearchField value={query} onChange={setQuery} placeholder={t("qz.hub.search")} className="w-full sm:w-56" />
              <Select aria-label={t("qz.col.course")} value={course} onChange={(event) => setCourse(event.target.value)} className="max-w-[12rem]">
                <option value="">{t("qz.hub.allCourses")}</option>
                {subjects.map((subject) => (
                  <option key={subject.id} value={subject.id}>
                    {subject.name}
                  </option>
                ))}
              </Select>
              <Select
                aria-label={t("qz.col.status")}
                value={status}
                onChange={(event) => setStatus(event.target.value as StatusFilter)}
              >
                <option value="all">{t("qzx.filter.active")}</option>
                <option value="ready">{t("qzx.st.ready")}</option>
                <option value="in_progress">{t("qzx.st.in_progress")}</option>
                <option value="completed">{t("qzx.st.completed")}</option>
                <option value="archived">{`${t("qzx.st.archived")} (${archivedCount})`}</option>
                <option value="writing">{t("qzx.st.preparing")}</option>
                <option value="failed">{t("qzx.st.failed")}</option>
              </Select>
              <button
                type="button"
                aria-pressed={openOnly}
                onClick={() => setOpenOnly((value) => !value)}
                className={`h-10 rounded-control border px-3 text-sm ${
                  openOnly ? "border-primary bg-primary-soft font-medium text-brand" : "border-border-strong bg-surface text-muted hover:text-ink"
                }`}
              >
                {t("qz.hub.inProgressOnly")}
                <span className="tabular ml-1.5 text-faint">{openCount}</span>
              </button>
            </div>
          ) : null}

          {failed && !quizzes ? (
            <div className="p-3.5">
              <ErrorState compact onRetry={() => void load()} />
            </div>
          ) : quizzes === null ? (
            <div className="space-y-2 p-3.5" role="status" aria-label={t("common.loading")}>
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={i} className="h-9 w-full" />
              ))}
            </div>
          ) : quizzes.length === 0 ? (
            <div className="p-3.5">
              <EmptyState title={t("qz.hub.emptyTitle")} description={t("quiz.list.empty")} compact>
                <Button onClick={() => setCreating(true)}>
                  <Plus className="h-4 w-4" aria-hidden />
                  {t("quiz.create.button")}
                </Button>
              </EmptyState>
            </div>
          ) : shown.length === 0 ? (
            <div className="p-3.5">
              <NoResults title={t("qz.hub.noResults")} description={t("qz.hub.noResultsBody")}>
                <Button variant="secondary" onClick={clearFilters}>
                  {t("qz.hub.clear")}
                </Button>
              </NoResults>
            </div>
          ) : (
            <QuizTable quizzes={shown} busyId={busyId} onStart={(quiz) => void start(quiz)} onRetry={(quiz) => void retry(quiz)}
              onDelete={setToDelete}
              onArchive={setToArchive}
              onRestore={(quiz) => void setArchived(quiz, false)}
            />
          )}
          {failed && quizzes ? <p className="border-t border-border px-3.5 py-2 text-xs text-danger">{t("qz.hub.staleBody")}</p> : null}
        </Panel>

        <HubSidebar progress={progress} course={course} subjects={subjects} onStarted={(attemptId) => router.push(`/quizzes/attempt/${attemptId}`)} />
      </div>

      <CreateQuizDialog
        open={creating}
        onClose={() => setCreating(false)}
        subjects={subjects}
        defaultCourse={course || initialCourse}
        dueBySubject={dueBySubject}
        onCreated={() => {
          setCreating(false);
          toast.success(t("quiz.create.started"));
          void load();
        }}
        onRevision={(attemptId) => router.push(`/quizzes/attempt/${attemptId}`)}
      />

      <ConfirmDialog
        open={toArchive !== null}
        tone="primary"
        title={t("qzx.archive")}
        description={t("qzx.archiveConfirm", { name: toArchive?.title ?? "" })}
        confirmLabel={t("qzx.archive")}
        onConfirm={async () => {
          if (toArchive) await setArchived(toArchive, true);
        }}
        onClose={() => setToArchive(null)}
      />

      <ConfirmDialog
        open={toDelete !== null}
        title={t("common.delete")}
        description={t("quiz.list.deleteConfirm", { name: toDelete?.title ?? "" })}
        confirmLabel={t("common.delete")}
        onConfirm={() => remove()}
        onClose={() => setToDelete(null)}
      />
    </div>
  );
}
