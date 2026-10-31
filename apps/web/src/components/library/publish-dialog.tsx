"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Button, FormRow, Input, Select, Textarea } from "@/components/kit";
import { Alert } from "@/components/ui";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { RIGHTS, RIGHTS_KEYS, formatSize } from "@/lib/groups";
import { DOC_TYPES, DOC_TYPE_KEYS, VISIBILITIES, VISIBILITY_HELP_KEYS, VISIBILITY_KEYS } from "@/lib/library";
import type { LibraryDocType, LibraryItem, LibraryVisibility, ShareRights, User } from "@/lib/types";

type Shareable = { id: string; filename: string; kind: string; size_bytes: number | null; subject_name: string };

/** Publish one of the student's files, or edit how an existing library file is described and who
 *  may see it. The audience choice is the point of this dialog, so it is spelled out. */
export function PublishDialog({
  open,
  user,
  item,
  onClose,
  onSaved,
}: {
  open: boolean;
  user: User;
  /** Set when editing; null to publish a new file. */
  item: LibraryItem | null;
  onClose: () => void;
  onSaved: (saved: LibraryItem) => void;
}) {
  const t = useT();
  const editing = item !== null;
  const [files, setFiles] = useState<Shareable[] | null>(null);
  const [materialId, setMaterialId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [docType, setDocType] = useState<LibraryDocType>("notes");
  const [course, setCourse] = useState("");
  const [topic, setTopic] = useState("");
  const [semester, setSemester] = useState("");
  const [year, setYear] = useState("");
  const [author, setAuthor] = useState("");
  const [rights, setRights] = useState<ShareRights>("own_work");
  const [visibility, setVisibility] = useState<LibraryVisibility>("private");
  const [confirmRights, setConfirmRights] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Start from the item being edited, or from an empty form.
  useEffect(() => {
    if (!open) return;
    setError(null);
    setConfirmRights(false);
    setMaterialId("");
    setTitle(item?.title ?? "");
    setDescription(item?.description ?? "");
    setDocType(item?.doc_type ?? "notes");
    setCourse(item?.course_name ?? "");
    setTopic(item?.topic ?? "");
    setSemester(item?.semester ?? "");
    setYear(item?.academic_year ?? "");
    setAuthor(item?.author ?? "");
    setRights(item?.rights ?? "own_work");
    setVisibility(item?.visibility ?? "private");
  }, [open, item]);

  useEffect(() => {
    if (!open || editing) return;
    api<Shareable[]>("/shareable-materials")
      .then(setFiles)
      .catch((caught: unknown) => setError(errorMessage(caught, t)));
  }, [open, editing, t]);

  const widening = editing ? visibility !== "private" && visibility !== item?.visibility : visibility !== "private";
  const needsInstitution = visibility === "institution" && !user.institution_name;
  const canSave =
    !busy &&
    !needsInstitution &&
    (editing || materialId !== "") &&
    (title.trim().length >= 2 || (!editing && title.trim() === "")) &&
    (!widening || confirmRights);

  function pick(id: string) {
    setMaterialId(id);
    const file = files?.find((f) => f.id === id);
    if (file) {
      if (!course) setCourse(file.subject_name);
      if (!title) setTitle(file.filename.replace(/\.[^.]+$/, ""));
      if (file.kind === "past_paper") setDocType("past_paper");
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSave) return;
    setBusy(true);
    setError(null);
    const fields = {
      title: title.trim() || undefined,
      description: description.trim(),
      doc_type: docType,
      course_name: course.trim(),
      topic: topic.trim(),
      semester: semester.trim(),
      academic_year: year.trim(),
      author: author.trim(),
      rights,
      visibility,
      confirm_rights: confirmRights,
    };
    try {
      const saved = item
        ? await api<LibraryItem>(`/library/${item.id}`, { method: "PATCH", body: fields })
        : await api<LibraryItem>("/library", { method: "POST", body: { ...fields, material_id: materialId } });
      onSaved(saved);
      onClose();
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={editing ? t("ml.edit.title") : t("ml.publish.title")} wide>
      <form onSubmit={submit} className="space-y-4">
        {!editing ? (
          <FormRow label={t("ml.publish.file")} htmlFor="ml-file" hint={t("ml.publish.fileHint")}>
            <Select id="ml-file" className="w-full" value={materialId} onChange={(e) => pick(e.target.value)} required>
              <option value="">{files === null ? t("common.loading") : t("ml.publish.choose")}</option>
              {(files ?? [])
                .filter((f) => f.kind !== "assignment")
                .map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.subject_name} · {f.filename}
                    {f.size_bytes !== null ? ` (${formatSize(f.size_bytes)})` : ""}
                  </option>
                ))}
            </Select>
          </FormRow>
        ) : (
          <p className="truncate text-sm text-muted">{item?.filename}</p>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <FormRow label={t("ml.field.title")} htmlFor="ml-title" className="sm:col-span-2">
            <Input id="ml-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={160} />
          </FormRow>
          <FormRow label={t("ml.field.type")} htmlFor="ml-type">
            <Select id="ml-type" className="w-full" value={docType} onChange={(e) => setDocType(e.target.value as LibraryDocType)}>
              {DOC_TYPES.map((type) => (
                <option key={type} value={type}>
                  {t(DOC_TYPE_KEYS[type])}
                </option>
              ))}
            </Select>
          </FormRow>
          <FormRow label={t("ml.field.course")} htmlFor="ml-course">
            <Input id="ml-course" value={course} onChange={(e) => setCourse(e.target.value)} maxLength={120} />
          </FormRow>
          <FormRow label={t("ml.field.topic")} htmlFor="ml-topic">
            <Input id="ml-topic" value={topic} onChange={(e) => setTopic(e.target.value)} maxLength={120} />
          </FormRow>
          <FormRow label={t("ml.field.author")} htmlFor="ml-author">
            <Input id="ml-author" value={author} onChange={(e) => setAuthor(e.target.value)} maxLength={120} />
          </FormRow>
          <FormRow label={t("ml.field.semester")} htmlFor="ml-sem">
            <Input id="ml-sem" value={semester} onChange={(e) => setSemester(e.target.value)} maxLength={20} />
          </FormRow>
          <FormRow label={t("ml.field.year")} htmlFor="ml-year" hint={t("ml.field.yearHint")}>
            <Input id="ml-year" value={year} onChange={(e) => setYear(e.target.value)} maxLength={20} placeholder="2025-26" />
          </FormRow>
          <FormRow label={t("ml.field.description")} htmlFor="ml-desc" className="sm:col-span-2">
            <Textarea id="ml-desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={600} />
          </FormRow>
        </div>

        <fieldset className="space-y-2 rounded-xl border border-border p-3">
          <legend className="px-1 text-[13px] font-medium">{t("ml.vis.label")}</legend>
          {VISIBILITIES.map((option) => (
            <label key={option} className="flex items-start gap-2 text-sm">
              <input
                type="radio"
                name="ml-visibility"
                className="mt-1"
                checked={visibility === option}
                onChange={() => setVisibility(option)}
              />
              <span>
                <span className="font-medium">{t(VISIBILITY_KEYS[option])}</span>
                <span className="block text-xs text-muted">{t(VISIBILITY_HELP_KEYS[option])}</span>
              </span>
            </label>
          ))}
        </fieldset>

        {needsInstitution ? <Alert tone="info">{t("ml.needInstitution")}</Alert> : null}

        {visibility !== "private" ? (
          <div className="space-y-3 rounded-xl border border-border bg-surface-2 p-3">
            <FormRow label={t("lg.rights.label")} htmlFor="ml-rights">
              <Select id="ml-rights" className="w-full" value={rights} onChange={(e) => setRights(e.target.value as ShareRights)}>
                {RIGHTS.map((right) => (
                  <option key={right} value={right}>
                    {t(RIGHTS_KEYS[right])}
                  </option>
                ))}
              </Select>
            </FormRow>
            {widening ? (
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={confirmRights} onChange={(e) => setConfirmRights(e.target.checked)} />
                <span>{t("ml.confirmRights")}</span>
              </label>
            ) : null}
            {visibility === "public" ? <p className="text-xs text-muted">{t("ml.reviewNote")}</p> : null}
          </div>
        ) : null}

        {error ? <Alert>{error}</Alert> : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy} disabled={!canSave}>
            {editing ? t("common.save") : t("ml.publish.submit")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
