"use client";

import clsx from "clsx";
import { AlertCircle, CheckCircle2, FileText, Loader2, UploadCloud, X } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Button } from "@/components/kit/button";
import { FormRow, Select } from "@/components/kit/controls";
import { useToast } from "@/components/kit/toast";
import { useT } from "@/i18n/client";
import { uploadMaterial } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { formatBytes } from "@/lib/format";
import type { MaterialKind } from "@/lib/types";

import { ModuleInput } from "./material-actions";
import { ACCEPTED_EXTENSIONS, KINDS, KIND_KEYS, MAX_UPLOAD_MB, fileExtension } from "./model";

type Entry = {
  key: string;
  file: File;
  state: "queued" | "uploading" | "done" | "error";
  message: string | null;
};

let counter = 0;

/** Choose or drop files, say what they are and which module they belong to, and upload them one
 *  after another. Files that fail validation or upload stay listed with the reason. */
export function UploadDialog({
  open,
  onClose,
  subjectId,
  defaultKind,
  defaultModule,
  initialFiles,
  modules,
  onUploaded,
}: {
  open: boolean;
  onClose: () => void;
  subjectId: string;
  defaultKind: MaterialKind;
  defaultModule: string;
  initialFiles: File[];
  modules: string[];
  onUploaded: () => void;
}) {
  const t = useT();
  return (
    <Dialog open={open} onClose={onClose} title={t("sj.upload.title")}>
      {open ? (
        <UploadForm
          subjectId={subjectId}
          defaultKind={defaultKind}
          defaultModule={defaultModule}
          initialFiles={initialFiles}
          modules={modules}
          onClose={onClose}
          onUploaded={onUploaded}
        />
      ) : null}
    </Dialog>
  );
}

function UploadForm({
  subjectId,
  defaultKind,
  defaultModule,
  initialFiles,
  modules,
  onClose,
  onUploaded,
}: {
  subjectId: string;
  defaultKind: MaterialKind;
  defaultModule: string;
  initialFiles: File[];
  modules: string[];
  onClose: () => void;
  onUploaded: () => void;
}) {
  const t = useT();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<MaterialKind>(defaultKind);
  const [module, setModule] = useState(defaultModule);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [entries, setEntries] = useState<Entry[]>(() => initialFiles.map(checked));

  function checked(file: File): Entry {
    let message: string | null = null;
    if (!ACCEPTED_EXTENSIONS.includes(fileExtension(file.name))) message = t("errors.unsupported_type");
    else if (file.size > MAX_UPLOAD_MB * 1024 * 1024) message = t("errors.file_too_large");
    else if (file.size === 0) message = t("errors.empty_file");
    counter += 1;
    return { key: `${counter}-${file.name}`, file, state: message ? "error" : "queued", message };
  }

  function add(files: File[]) {
    setEntries((current) => [...current.filter((entry) => entry.state !== "done"), ...files.map(checked)]);
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    add(Array.from(event.dataTransfer.files));
  }

  const update = (key: string, patch: Partial<Entry>) =>
    setEntries((current) => current.map((entry) => (entry.key === key ? { ...entry, ...patch } : entry)));

  async function submit() {
    setBusy(true);
    let uploaded = 0;
    let failed = 0;
    for (const entry of entries) {
      if (entry.state !== "queued") {
        if (entry.state === "error") failed += 1;
        continue;
      }
      update(entry.key, { state: "uploading" });
      try {
        await uploadMaterial(subjectId, entry.file, kind, module);
        update(entry.key, { state: "done" });
        uploaded += 1;
      } catch (caught) {
        update(entry.key, { state: "error", message: errorMessage(caught, t) });
        failed += 1;
      }
    }
    setBusy(false);
    if (uploaded > 0) {
      onUploaded();
      toast.success(t("sj.upload.done", { count: uploaded }));
    }
    if (failed === 0) onClose();
  }

  const queued = entries.filter((entry) => entry.state === "queued").length;

  return (
    <div className="space-y-4">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={clsx(
          "flex flex-col items-center rounded border border-dashed px-4 py-5 text-center",
          dragging ? "border-primary bg-primary-soft" : "border-border-strong bg-surface-2",
        )}
      >
        <UploadCloud className="h-5 w-5 text-faint" aria-hidden />
        <p className="mt-1.5 text-[13px] font-medium">{t("materials.dropTitle")}</p>
        <p className="mt-0.5 text-xs text-muted">{t("materials.dropHint", { mb: MAX_UPLOAD_MB })}</p>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          aria-label={t("materials.choose")}
          data-testid="upload-input"
          accept={ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`).join(",")}
          onChange={(event) => {
            add(Array.from(event.target.files ?? []));
            event.target.value = "";
          }}
        />
        <Button variant="secondary" size="sm" className="mt-3" onClick={() => input.current?.click()} disabled={busy}>
          {t("materials.choose")}
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <FormRow label={t("sj.col.type")} htmlFor="upload-kind">
          <Select id="upload-kind" value={kind} onChange={(event) => setKind(event.target.value as MaterialKind)} className="w-full" disabled={busy}>
            {KINDS.map((value) => (
              <option key={value} value={value}>
                {t(KIND_KEYS[value])}
              </option>
            ))}
          </Select>
        </FormRow>
        <FormRow label={t("sj.col.module")} htmlFor="upload-module">
          <ModuleInput id="upload-module" value={module} onChange={setModule} modules={modules} />
        </FormRow>
      </div>

      {entries.length > 0 ? (
        <ul className="divide-y divide-border rounded border border-border text-[13px]">
          {entries.map((entry) => (
            <li key={entry.key} className="flex items-start gap-2 px-2.5 py-1.5">
              <FileText className="mt-0.5 h-4 w-4 shrink-0 text-faint" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="break-all">{entry.file.name}</p>
                <p className={clsx("text-xs", entry.state === "error" ? "text-danger" : "text-muted")}>
                  {entry.state === "error" ? entry.message : formatBytes(entry.file.size)}
                </p>
              </div>
              {entry.state === "uploading" ? <Loader2 className="mt-0.5 h-4 w-4 animate-spin text-muted" aria-label={t("common.loading")} /> : null}
              {entry.state === "done" ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-success" aria-label={t("sj.upload.uploaded")} /> : null}
              {entry.state === "error" ? <AlertCircle className="mt-0.5 h-4 w-4 text-danger" aria-hidden /> : null}
              {entry.state === "queued" || entry.state === "error" ? (
                <button
                  type="button"
                  onClick={() => setEntries((current) => current.filter((item) => item.key !== entry.key))}
                  aria-label={t("sj.upload.remove", { name: entry.file.name })}
                  disabled={busy}
                  className="rounded p-0.5 text-muted hover:bg-surface-3 hover:text-ink disabled:opacity-40"
                >
                  <X className="h-3.5 w-3.5" aria-hidden />
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="flex justify-end gap-2 pt-1">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          {t("common.cancel")}
        </Button>
        <Button onClick={() => void submit()} loading={busy} disabled={queued === 0} title={queued === 0 ? t("sj.upload.nothing") : undefined}>
          {t("sj.upload.submit", { count: queued })}
        </Button>
      </div>
    </div>
  );
}
