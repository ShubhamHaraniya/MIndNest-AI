"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Button } from "@/components/kit/button";
import { FormRow, Input, Textarea } from "@/components/kit/controls";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { DeleteImpact, Subject } from "@/lib/types";

/** The fields a course form edits. */
export type CourseDraft = Pick<Subject, "id" | "name" | "course_code" | "semester" | "description">;

export function CourseFormDialog({
  open,
  course,
  onClose,
  onSaved,
}: {
  open: boolean;
  /** The course to edit, or null to create one. */
  course: CourseDraft | null;
  onClose: () => void;
  onSaved: (saved: Subject, created: boolean) => void;
}) {
  const t = useT();
  return (
    <Dialog open={open} onClose={onClose} title={course ? t("subjects.editTitle") : t("subjects.createTitle")}>
      {/* Keyed so the form starts fresh each time the dialog opens for a different course. */}
      {open ? <CourseForm key={course?.id ?? "new"} course={course} onCancel={onClose} onSaved={onSaved} /> : null}
    </Dialog>
  );
}

function CourseForm({
  course,
  onCancel,
  onSaved,
}: {
  course: CourseDraft | null;
  onCancel: () => void;
  onSaved: (saved: Subject, created: boolean) => void;
}) {
  const t = useT();
  const [name, setName] = useState(course?.name ?? "");
  const [code, setCode] = useState(course?.course_code ?? "");
  const [semester, setSemester] = useState(course?.semester ?? "");
  const [description, setDescription] = useState(course?.description ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    const body = {
      name,
      course_code: code || null,
      semester: semester || null,
      description: description || null,
    };
    try {
      const saved = course
        ? await api<Subject>(`/subjects/${course.id}`, { method: "PATCH", body })
        : await api<Subject>("/subjects", { method: "POST", body });
      onSaved(saved, course === null);
    } catch (caught) {
      setError(errorMessage(caught, t));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4">
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      <FormRow label={t("subjects.fieldName")} htmlFor="course-name">
        <Input id="course-name" required maxLength={120} autoFocus value={name} onChange={(event) => setName(event.target.value)} />
      </FormRow>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormRow label={`${t("subjects.fieldCode")} (${t("common.optional")})`} htmlFor="course-code">
          <Input id="course-code" maxLength={40} value={code} onChange={(event) => setCode(event.target.value)} />
        </FormRow>
        <FormRow label={`${t("subjects.fieldSemester")} (${t("common.optional")})`} htmlFor="course-semester">
          <Input id="course-semester" maxLength={40} value={semester} onChange={(event) => setSemester(event.target.value)} />
        </FormRow>
      </div>
      <FormRow label={`${t("subjects.fieldDescription")} (${t("common.optional")})`} htmlFor="course-description">
        <Textarea id="course-description" rows={3} maxLength={2000} value={description} onChange={(event) => setDescription(event.target.value)} />
      </FormRow>
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="secondary" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
        <Button type="submit" loading={busy} disabled={!name.trim()}>
          {course ? t("common.save") : t("common.create")}
        </Button>
      </div>
    </form>
  );
}

/** Deleting a course also deletes its files, so the dialog first asks the server what would go. */
export function DeleteCourseDialog({
  course,
  onClose,
  onDeleted,
}: {
  course: Pick<Subject, "id" | "name"> | null;
  onClose: () => void;
  onDeleted: (id: string) => void;
}) {
  const t = useT();
  const [impact, setImpact] = useState<DeleteImpact | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const id = course?.id ?? null;

  useEffect(() => {
    setImpact(null);
    setError(null);
    setBusy(false);
    if (!id) return;
    const controller = new AbortController();
    api<DeleteImpact>(`/subjects/${id}/delete-impact`, { signal: controller.signal })
      .then(setImpact)
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorMessage(caught, t));
      });
    return () => controller.abort();
  }, [id, t]);

  async function confirm() {
    if (!id) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/subjects/${id}?confirm=true`, { method: "DELETE" });
      onDeleted(id);
    } catch (caught) {
      setError(errorMessage(caught, t));
      setBusy(false);
    }
  }

  const hasContent = impact !== null && (impact.materials > 0 || impact.topics > 0);

  return (
    <Dialog open={course !== null} onClose={onClose} title={t("subjects.deleteTitle", { name: course?.name ?? "" })}>
      <div className="space-y-4">
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        ) : null}
        {impact ? (
          <>
            {hasContent ? (
              <>
                <p className="text-sm">{t("subjects.deleteBody")}</p>
                <ul className="list-disc space-y-1 pl-5 text-sm">
                  {impact.materials > 0 ? <li>{t("subjects.deleteMaterials", { count: impact.materials })}</li> : null}
                  {impact.topics > 0 ? <li>{t("subjects.deleteTopics", { count: impact.topics })}</li> : null}
                </ul>
              </>
            ) : (
              <p className="text-sm">{t("subjects.deleteNothing")}</p>
            )}
            {impact.conversations_kept > 0 ? (
              <p className="text-sm text-muted">{t("subjects.deleteChats", { count: impact.conversations_kept })}</p>
            ) : null}
          </>
        ) : error ? null : (
          <p className="text-sm text-muted">{t("common.loading")}</p>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button variant="danger" onClick={() => void confirm()} loading={busy} disabled={!impact}>
            {t("subjects.deleteConfirm")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
