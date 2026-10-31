"use client";

import { Download } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Badge, Button, FormRow, Select, Textarea, buttonClass } from "@/components/kit";
import { Alert } from "@/components/ui";
import { useT } from "@/i18n/client";
import type { MessageKey } from "@/i18n/translate";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { REPORT_REASONS, formatSize } from "@/lib/groups";
import { DOC_TYPE_KEYS, fileUrl } from "@/lib/library";
import type { LibraryItem, ReportReason, Subject, SubjectPage } from "@/lib/types";

/** The file itself in a frame (PDF, picture or text) next to who it is from. */
export function PreviewDialog({ item, onClose }: { item: LibraryItem | null; onClose: () => void }) {
  const t = useT();
  return (
    <Dialog open={item !== null} onClose={onClose} title={item?.title ?? ""} wide>
      {item ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <Badge>{t(DOC_TYPE_KEYS[item.doc_type])}</Badge>
            {item.course_name ? <span>{item.course_name}</span> : null}
            {item.institution ? <span>· {item.institution}</span> : null}
            {item.author ? <span>· {t("ml.by", { author: item.author })}</span> : null}
            {item.size_bytes !== null ? <span>· {formatSize(item.size_bytes)}</span> : null}
          </div>
          {item.previewable ? (
            <iframe
              title={item.title}
              src={fileUrl(item.id, true)}
              className="h-[60vh] w-full rounded-xl border border-border bg-surface"
            />
          ) : (
            <Alert tone="info">{t("ml.noPreview")}</Alert>
          )}
          <div className="flex justify-end">
            <a href={fileUrl(item.id)} className={buttonClass("secondary")}>
              <Download className="h-3.5 w-3.5" aria-hidden />
              {t("lib.file.download")}
            </a>
          </div>
        </div>
      ) : null}
    </Dialog>
  );
}

/** Copy a library file into one of the student's own subjects, where it is read like any upload. */
export function AddDialog({
  item,
  onClose,
  onDone,
}: {
  item: LibraryItem | null;
  onClose: () => void;
  onDone: (subjectId: string) => void;
}) {
  const t = useT();
  const [subjects, setSubjects] = useState<Subject[] | null>(null);
  const [subjectId, setSubjectId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = item !== null;

  useEffect(() => {
    if (!open) return;
    setError(null);
    api<SubjectPage>("/subjects?limit=100")
      .then((page) => {
        const active = page.items.filter((s) => !s.archived_at);
        setSubjects(active);
        setSubjectId(active[0]?.id ?? "");
      })
      .catch((caught: unknown) => setError(errorMessage(caught, t)));
  }, [open, t]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!item || !subjectId) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/library/${item.id}/add`, { method: "POST", body: { subject_id: subjectId } });
      onDone(subjectId);
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("ml.add.title")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        <p className="text-sm text-muted">{t("ml.add.intro")}</p>
        {error ? <Alert>{error}</Alert> : null}
        {subjects !== null && subjects.length === 0 ? (
          <p className="text-sm text-muted">{t("lib.add.nosubjects")}</p>
        ) : (
          <FormRow label={t("lib.add.subject")} htmlFor="ml-add-subject">
            <Select id="ml-add-subject" className="w-full" value={subjectId} onChange={(e) => setSubjectId(e.target.value)}>
              {(subjects ?? []).map((subject) => (
                <option key={subject.id} value={subject.id}>
                  {subject.name}
                </option>
              ))}
            </Select>
          </FormRow>
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy} disabled={!subjectId}>
            {t("ml.add.submit")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function ReportDialog({
  item,
  onClose,
  onDone,
}: {
  item: LibraryItem | null;
  onClose: () => void;
  onDone: (held: boolean) => void;
}) {
  const t = useT();
  const [reason, setReason] = useState<ReportReason>("copyright");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = item !== null;

  useEffect(() => {
    if (open) {
      setError(null);
      setNote("");
      setReason("copyright");
    }
  }, [open]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!item) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ held: boolean }>(`/library/${item.id}/report`, {
        method: "POST",
        body: { reason, note },
      });
      onDone(result.held);
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("lib.report.title")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        <p className="text-sm text-muted">{t("ml.report.intro")}</p>
        {error ? <Alert>{error}</Alert> : null}
        <fieldset className="space-y-2">
          <legend className="mb-1.5 text-sm font-medium">{t("lib.report.reason")}</legend>
          {REPORT_REASONS.map((value) => (
            <label key={value} className="flex items-start gap-3 text-sm">
              <input
                type="radio"
                name="ml-report-reason"
                className="mt-1"
                checked={reason === value}
                onChange={() => setReason(value)}
              />
              <span>{t(`lib.report.reason.${value}` as MessageKey)}</span>
            </label>
          ))}
        </fieldset>
        <FormRow label={t("lib.report.note")} htmlFor="ml-report-note">
          <Textarea id="ml-report-note" rows={3} maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
        </FormRow>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy}>
            {t("lib.report.submit")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
