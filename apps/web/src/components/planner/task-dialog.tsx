"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Button } from "@/components/kit/button";
import { FormRow, Input, Select } from "@/components/kit/controls";
import { useT } from "@/i18n/client";
import { taskTitle } from "@/lib/planner";
import type { StudyTask, Subject } from "@/lib/types";

import type { NewTask, TaskPatch } from "./use-planner";

const MIN = 5;
const MAX = 480;

/** Add a task of your own, or change the day, length, title and course of one. A task the
 *  planner made keeps its title and course; moving or resizing it pins it so it stays when the
 *  plan is made again. */
export function TaskDialog({
  open,
  task,
  defaultDay,
  subjects,
  onClose,
  onAdd,
  onUpdate,
}: {
  open: boolean;
  task: StudyTask | null;
  defaultDay: string;
  subjects: Subject[];
  onClose: () => void;
  onAdd: (draft: NewTask) => Promise<boolean>;
  onUpdate: (task: StudyTask, patch: TaskPatch) => Promise<boolean>;
}) {
  const t = useT();
  const planned = task?.source === "plan";
  const [title, setTitle] = useState("");
  const [day, setDay] = useState(defaultDay);
  const [minutes, setMinutes] = useState(30);
  const [subjectId, setSubjectId] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setTitle(task ? taskTitle(task, t) : "");
    setDay(task ? task.planned_for : defaultDay);
    setMinutes(task ? task.minutes : 30);
    setSubjectId(task?.subject_id ?? "");
    setBusy(false);
  }, [open, task, defaultDay, t]);

  const valid = day !== "" && minutes >= MIN && minutes <= MAX && (planned || title.trim() !== "");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    let ok: boolean;
    if (task === null) {
      ok = await onAdd({ title: title.trim(), planned_for: day, minutes, subject_id: subjectId || null });
    } else {
      const patch: TaskPatch = {};
      if (day !== task.planned_for) patch.planned_for = day;
      if (minutes !== task.minutes) patch.minutes = minutes;
      if (!planned) {
        if (title.trim() !== task.title) patch.title = title.trim();
        if ((subjectId || null) !== task.subject_id) patch.subject_id = subjectId || null;
      }
      ok = Object.keys(patch).length === 0 ? true : await onUpdate(task, patch);
    }
    setBusy(false);
    if (ok) onClose();
  }

  return (
    <Dialog open={open} onClose={onClose} title={task ? t("pl.dialog.edit") : t("pl.dialog.add")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        <FormRow label={t("planner.add.what")} htmlFor="task-title" hint={planned ? t("pl.dialog.plannedHint") : undefined}>
          <Input
            id="task-title"
            autoFocus={!planned}
            value={title}
            maxLength={120}
            disabled={planned}
            onChange={(event) => setTitle(event.target.value)}
          />
        </FormRow>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormRow label={t("planner.add.day")} htmlFor="task-day">
            <Input id="task-day" type="date" value={day} onChange={(event) => setDay(event.target.value)} required />
          </FormRow>
          <FormRow label={t("planner.add.minutes")} htmlFor="task-minutes" hint={t("pl.dialog.minutesHint", { min: MIN, max: MAX })}>
            <Input
              id="task-minutes"
              type="number"
              min={MIN}
              max={MAX}
              step={5}
              value={minutes}
              onChange={(event) => setMinutes(Number(event.target.value) || 0)}
            />
          </FormRow>
        </div>
        <FormRow label={t("assign.create.subject")} htmlFor="task-subject">
          <Select id="task-subject" value={subjectId} disabled={planned} onChange={(event) => setSubjectId(event.target.value)}>
            <option value="">{t("planner.exams.noSubject")}</option>
            {subjects.map((subject) => (
              <option key={subject.id} value={subject.id}>
                {subject.name}
              </option>
            ))}
          </Select>
        </FormRow>
        {planned ? <p className="text-xs text-muted">{t("pl.dialog.pinNote")}</p> : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy} disabled={!valid}>
            {task ? t("common.save") : t("planner.add.button")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
