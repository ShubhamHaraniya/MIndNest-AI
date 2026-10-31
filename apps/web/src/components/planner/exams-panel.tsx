"use client";

import { GraduationCap, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { ConfirmDialog } from "@/components/kit/confirm";
import { FormRow, Input, Select } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { useToast } from "@/components/kit/toast";
import { IconButton } from "@/components/subjects/bits";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { parseDay } from "@/lib/planner";
import type { Exam, Subject } from "@/lib/types";

/** The exams the plan builds revision around: add, change the date, remove. */
export function ExamsPanel({
  exams,
  subjects,
  onChanged,
}: {
  exams: Exam[];
  subjects: Subject[];
  onChanged: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const toast = useToast();
  const [editing, setEditing] = useState<Exam | "new" | null>(null);
  const [removing, setRemoving] = useState<Exam | null>(null);

  async function remove() {
    if (!removing) return;
    try {
      await api(`/exams/${removing.id}`, { method: "DELETE" });
      onChanged();
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  return (
    <Panel
      id="exams"
      title={t("planner.exams.title")}
      description={t("planner.exams.intro")}
      action={
        <Button size="sm" variant="secondary" onClick={() => setEditing("new")}>
          <Plus className="h-3.5 w-3.5" aria-hidden />
          {t("planner.exams.add")}
        </Button>
      }
    >
      {exams.length === 0 ? (
        <p className="flex items-center gap-2 px-3.5 py-5 text-[13px] text-muted">
          <GraduationCap className="h-4 w-4 shrink-0" aria-hidden />
          {t("pl.exams.empty")}
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {exams.map((exam) => (
            <li key={exam.id} className="flex items-center justify-between gap-3 px-3.5 py-2.5 text-[13px]">
              <div className="min-w-0">
                <p className="truncate font-medium">{exam.title}</p>
                <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted">
                  <span>{parseDay(exam.exam_on).toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric" })}</span>
                  {exam.subject_name ? <span>{exam.subject_name}</span> : null}
                  {exam.days_left < 0 ? (
                    <Badge>{t("planner.exams.past")}</Badge>
                  ) : (
                    <Badge tone={exam.days_left <= 3 ? "warning" : "neutral"}>
                      {exam.days_left === 0 ? t("planner.exams.today") : t("planner.exams.daysLeft", { count: exam.days_left })}
                    </Badge>
                  )}
                </p>
              </div>
              <span className="inline-flex shrink-0 gap-0.5">
                <IconButton label={t("pl.edit")} onClick={() => setEditing(exam)}>
                  <Pencil className="h-3.5 w-3.5" aria-hidden />
                </IconButton>
                <IconButton label={t("common.delete")} danger onClick={() => setRemoving(exam)}>
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                </IconButton>
              </span>
            </li>
          ))}
        </ul>
      )}

      <ExamDialog
        exam={editing === "new" ? null : editing}
        open={editing !== null}
        subjects={subjects}
        onClose={() => setEditing(null)}
        onSaved={onChanged}
      />

      <ConfirmDialog
        open={removing !== null}
        title={t("pl.exams.removeTitle", { name: removing?.title ?? "" })}
        description={t("pl.exams.removeBody")}
        confirmLabel={t("common.delete")}
        onConfirm={remove}
        onClose={() => setRemoving(null)}
      />
    </Panel>
  );
}

function ExamDialog({
  exam,
  open,
  subjects,
  onClose,
  onSaved,
}: {
  exam: Exam | null;
  open: boolean;
  subjects: Subject[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT();
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setTitle(exam?.title ?? "");
    setDate(exam?.exam_on ?? "");
    setSubjectId(exam?.subject_id ?? "");
    setFailure(null);
  }, [open, exam]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim() || !date || busy) return;
    setBusy(true);
    setFailure(null);
    try {
      const body = { title: title.trim(), exam_on: date, subject_id: subjectId || null };
      if (exam) await api(`/exams/${exam.id}`, { method: "PATCH", body });
      else await api("/exams", { method: "POST", body });
      onSaved();
      onClose();
    } catch (caught) {
      setFailure(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={exam ? t("pl.exams.editTitle") : t("planner.exams.add")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {failure ? (
          <p role="alert" className="text-sm text-danger">
            {failure}
          </p>
        ) : null}
        <FormRow label={t("planner.exams.name")} htmlFor="exam-title">
          <Input id="exam-title" autoFocus value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} />
        </FormRow>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormRow label={t("planner.exams.date")} htmlFor="exam-date">
            <Input id="exam-date" type="date" value={date} onChange={(event) => setDate(event.target.value)} required />
          </FormRow>
          <FormRow label={t("assign.create.subject")} htmlFor="exam-subject">
            <Select id="exam-subject" value={subjectId} onChange={(event) => setSubjectId(event.target.value)}>
              <option value="">{t("planner.exams.noSubject")}</option>
              {subjects.map((subject) => (
                <option key={subject.id} value={subject.id}>
                  {subject.name}
                </option>
              ))}
            </Select>
          </FormRow>
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy} disabled={!title.trim() || !date}>
            {exam ? t("common.save") : t("planner.exams.add")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
