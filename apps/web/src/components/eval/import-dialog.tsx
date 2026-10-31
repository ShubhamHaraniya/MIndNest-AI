"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Button } from "@/components/kit/button";
import { FormRow, Input, Select } from "@/components/kit/controls";
import { useT } from "@/i18n/client";
import { ApiError, api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { EvalDataset, Subject } from "@/lib/types";

/** Bring in a question set from a .jsonl file. A bad file is explained line by line. */
export function ImportDialog({
  open,
  subjects,
  onClose,
  onDone,
}: {
  open: boolean;
  subjects: Subject[];
  onClose: () => void;
  onDone: (dataset: EvalDataset) => void;
}) {
  const t = useT();
  const fileRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [replace, setReplace] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);

  useEffect(() => {
    if (!open) return;
    setName("");
    setSubjectId("");
    setReplace(false);
    setMessage(null);
    setProblems([]);
    setBusy(false);
  }, [open]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const file = fileRef.current?.files?.[0];
    setMessage(null);
    setProblems([]);
    if (!file) {
      setMessage(t("eval.import.noFile"));
      return;
    }
    setBusy(true);
    try {
      const dataset = await api<EvalDataset>("/eval/datasets", {
        method: "POST",
        body: {
          name: name.trim() || file.name.replace(/\.[^.]+$/, ""),
          subject_id: subjectId || null,
          jsonl: await file.text(),
          replace,
        },
      });
      onDone(dataset);
    } catch (caught) {
      setMessage(errorMessage(caught, t));
      if (caught instanceof ApiError && caught.code === "invalid_dataset") {
        // Line-by-line problems are shown as the server wrote them (they quote the file).
        const details = caught.details as { errors?: string[] } | undefined;
        setProblems(details?.errors ?? []);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("eval.datasets.import")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        <p className="text-[13px] text-muted">{t("evx.import.intro")}</p>
        <FormRow label={t("eval.import.file")} htmlFor="import-file" hint={t("evx.import.fileHint")}>
          <input
            id="import-file"
            ref={fileRef}
            type="file"
            accept=".jsonl,.json,.txt,application/json"
            onChange={(event) => {
              const picked = event.target.files?.[0];
              if (picked && !name) setName(picked.name.replace(/\.[^.]+$/, ""));
            }}
            className="block w-full text-sm file:mr-3 file:rounded file:border file:border-border-strong file:bg-surface file:px-3 file:py-1.5 file:text-[13px] file:font-medium"
          />
        </FormRow>
        <FormRow label={t("eval.import.name")} htmlFor="import-name">
          <Input id="import-name" value={name} maxLength={80} onChange={(event) => setName(event.target.value)} />
        </FormRow>
        <FormRow label={t("eval.import.subject")} htmlFor="import-subject" hint={t("evx.import.subjectHint")}>
          <Select id="import-subject" value={subjectId} onChange={(event) => setSubjectId(event.target.value)}>
            <option value="">{t("eval.import.allSubjects")}</option>
            {subjects.map((subject) => (
              <option key={subject.id} value={subject.id}>
                {subject.name}
              </option>
            ))}
          </Select>
        </FormRow>
        <label className="flex items-start gap-2 text-[13px]">
          <input
            type="checkbox"
            checked={replace}
            onChange={(event) => setReplace(event.target.checked)}
            className="mt-0.5 h-4 w-4 accent-primary"
          />
          {t("eval.import.replace")}
        </label>
        {message ? (
          <p role="alert" className="text-sm text-danger">
            {message}
          </p>
        ) : null}
        {problems.length > 0 ? (
          <div className="rounded border border-border bg-surface-2 p-3 text-[13px]">
            <p className="font-medium">{t("eval.import.problems")}</p>
            <ul className="mt-1.5 max-h-40 list-disc space-y-0.5 overflow-y-auto pl-5 text-muted">
              {problems.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy}>
            {t("eval.import.submit")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
