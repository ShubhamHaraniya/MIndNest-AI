"use client";

import { Archive, ArchiveRestore, ChevronLeft, Crosshair, FileUp, ListChecks, MessageSquare, Pencil } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/kit/badge";
import { Button, ButtonLink } from "@/components/kit/button";
import { Textarea } from "@/components/kit/controls";
import { useLocale, useT } from "@/i18n/client";
import { percent, relativeTime } from "@/lib/format";
import type { Subject } from "@/lib/types";

import { dueText, microLabel } from "./bits";
import { hueOf } from "./course-card";
import type { CourseFigures, ProgressSummary } from "./model";

/** The course's name and details, its inline-editable description, the actions that start work
 *  (ask, quiz, upload) and a strip of facts about what is in it. */
export function CourseHeader({
  course,
  figures,
  summary,
  isCurrent,
  onAsk,
  onUpload,
  onEdit,
  onMakeCurrent,
  onToggleArchive,
  onSaveDescription,
}: {
  course: Subject;
  figures: CourseFigures | null;
  summary: ProgressSummary | null;
  isCurrent: boolean;
  onAsk: () => void;
  onUpload: () => void;
  onEdit: () => void;
  onMakeCurrent: () => void;
  onToggleArchive: () => void;
  onSaveDescription: (description: string | null) => Promise<void>;
}) {
  const t = useT();
  const locale = useLocale();
  const archived = course.archived_at !== null;

  const exam = figures?.next_exam_title && figures.next_exam_days !== null
    ? t("wb.course.examIn", { title: figures.next_exam_title, when: dueText(t, figures.next_exam_days) })
    : t("wb.course.noExam");
  const facts: { label: string; value: string; warn?: boolean }[] = figures
    ? [
        {
          label: t("wb.course.documents"),
          value: `${figures.documents}${figures.documents > 0 ? ` (${t("wb.course.ready", { ready: figures.documents_ready })})` : ""}`,
        },
        { label: t("wb.course.papers"), value: String(figures.past_papers) },
        { label: t("wb.course.notes"), value: String(figures.notes) },
        {
          label: t("wb.course.quizzes"),
          value: figures.quiz_attempts > 0 ? `${figures.quiz_attempts} · ${percent(figures.quiz_average)}` : "0",
        },
        {
          label: t("sj.col.accuracy"),
          value: summary && summary.answers > 0 ? `${percent(summary.accuracy)} · ${t("sj.progress.answers", { count: summary.answers })}` : "—",
          warn: summary !== null && summary.weak_documents > 0,
        },
        {
          label: t("wb.course.exam"),
          value: exam,
          warn: figures.next_exam_days !== null && figures.next_exam_days <= 7,
        },
      ]
    : [];

  return (
    <header className="glass sheen relative space-y-4 overflow-hidden rounded-3xl p-5 sm:p-7">
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-40"
        style={{ background: `radial-gradient(34rem 10rem at 12% 0%, color-mix(in srgb, var(--chart-${hueOf(course.id)}) 24%, transparent), transparent 70%)` }}
      />
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <Link href="/subjects" className="inline-flex items-center gap-0.5 text-xs text-muted hover:text-ink">
            <ChevronLeft className="h-3.5 w-3.5 rtl:rotate-180" aria-hidden />
            {t("subjects.back")}
          </Link>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <h1 className="font-display text-3xl leading-tight sm:text-4xl">{course.name}</h1>
            {isCurrent ? <Badge tone="brand">{t("sj.list.current")}</Badge> : null}
            {archived ? <Badge>{t("subjects.archivedBadge")}</Badge> : null}
          </div>
          <p className="mt-0.5 text-xs text-muted">
            {[course.course_code, course.semester].filter(Boolean).join(" · ")}
            {course.course_code || course.semester ? " · " : ""}
            {figures?.last_activity_at
              ? t("wb.course.lastActive", { when: relativeTime(figures.last_activity_at, locale) })
              : t("wb.course.noActivity")}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={onAsk}>
            <MessageSquare className="h-3.5 w-3.5" aria-hidden />
            {t("wb.course.ask")}
          </Button>
          <ButtonLink href={`/quizzes?subject=${course.id}`} variant="secondary">
            <ListChecks className="h-3.5 w-3.5" aria-hidden />
            {t("wb.course.quiz")}
          </ButtonLink>
          <Button variant="secondary" onClick={onUpload}>
            <FileUp className="h-3.5 w-3.5" aria-hidden />
            {t("sj.upload.button")}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <Description value={course.description} onSave={onSaveDescription} />
        <div className="flex flex-wrap items-center gap-1">
          <Button size="sm" variant="ghost" onClick={onEdit}>
            <Pencil className="h-3.5 w-3.5" aria-hidden />
            {t("sj.header.edit")}
          </Button>
          {!archived && !isCurrent ? (
            <Button size="sm" variant="ghost" onClick={onMakeCurrent}>
              <Crosshair className="h-3.5 w-3.5" aria-hidden />
              {t("sj.list.makeCurrent")}
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={onToggleArchive}>
            {archived ? <ArchiveRestore className="h-3.5 w-3.5" aria-hidden /> : <Archive className="h-3.5 w-3.5" aria-hidden />}
            {archived ? t("subjects.unarchive") : t("subjects.archive")}
          </Button>
        </div>
      </div>

      {facts.length > 0 ? (
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {facts.map((fact) => (
            <div key={fact.label} className="glass-flat min-w-0 rounded-2xl px-3.5 py-3">
              <dt className={microLabel()}>{fact.label}</dt>
              <dd className={`tabular mt-0.5 truncate text-sm font-medium ${fact.warn ? "text-warning" : ""}`} title={fact.value}>
                {fact.value}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <div className="glass-flat h-[4.25rem] rounded-2xl" aria-hidden />
      )}
    </header>
  );
}

/** Click to edit: the description is plain text until the student chooses to change it. */
function Description({ value, onSave }: { value: string | null; onSave: (description: string | null) => Promise<void> }) {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      await onSave(draft.trim() || null);
      setEditing(false);
    } catch {
      // The page shows the error as a toast; keep the draft so nothing is lost.
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <div className="w-full max-w-2xl space-y-2">
        <label htmlFor="course-desc" className="sr-only">
          {t("subjects.fieldDescription")}
        </label>
        <Textarea
          id="course-desc"
          rows={3}
          maxLength={2000}
          value={draft}
          autoFocus
          onChange={(event) => setDraft(event.target.value)}
          placeholder={t("sj.header.descriptionPlaceholder")}
        />
        <div className="flex gap-2">
          <Button size="sm" onClick={() => void save()} loading={busy}>
            {t("common.save")}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => {
              setDraft(value ?? "");
              setEditing(false);
            }}
          >
            {t("common.cancel")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-w-0 max-w-2xl flex-1 items-start gap-2">
      {value ? (
        <p className="min-w-0 whitespace-pre-line text-sm text-muted">{value}</p>
      ) : (
        <p className="text-sm text-faint">{t("sj.header.noDescription")}</p>
      )}
      <button
        type="button"
        onClick={() => {
          setDraft(value ?? "");
          setEditing(true);
        }}
        aria-label={t("sj.header.editDescription")}
        title={t("sj.header.editDescription")}
        className="mt-0.5 shrink-0 rounded p-0.5 text-faint hover:bg-surface-3 hover:text-ink"
      >
        <Pencil className="h-3.5 w-3.5" aria-hidden />
      </button>
    </div>
  );
}
