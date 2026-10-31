"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/kit/button";
import { FormRow, Input, Segmented, Textarea } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { useToast } from "@/components/kit/toast";
import { Markdown } from "@/components/markdown";
import { useT } from "@/i18n/client";
import { uploadMaterial } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Material } from "@/lib/types";

import { ModuleInput } from "./material-actions";
import { noteFilename } from "./model";

const TITLE_MAX = 120;
const BODY_MAX = 200_000;

/** Write a note in the browser. It is saved as a Markdown file in the course (through the normal
 *  upload), so it is read, searched, quizzed on and cited like any other document. */
export function NoteEditor({
  subjectId,
  modules,
  defaultModule,
  onCancel,
  onSaved,
}: {
  subjectId: string;
  modules: string[];
  defaultModule: string;
  onCancel: () => void;
  onSaved: (material: Material) => void;
}) {
  const t = useT();
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [module, setModule] = useState(defaultModule);
  const [body, setBody] = useState("");
  const [view, setView] = useState<"write" | "preview">("write");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = title.trim().length > 0 && body.trim().length > 0;
  // The title becomes the first heading, so the note reads well on its own and is cited by it.
  const markdown = `# ${title.trim()}\n\n${body.trim()}\n`;

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    const file = new File([markdown], noteFilename(title), { type: "text/markdown" });
    try {
      const saved = await uploadMaterial(subjectId, file, "note", module);
      toast.success(t("sj.note.saved", { name: saved.filename }));
      onSaved(saved);
    } catch (caught) {
      setError(errorMessage(caught, t));
      setBusy(false);
    }
  }

  return (
    <Panel
      id="note-editor"
      title={t("sj.note.title")}
      description={t("sj.note.help")}
      action={
        <Segmented
          label={t("sj.note.title")}
          value={view}
          onChange={setView}
          options={[
            { value: "write", label: t("sj.note.write") },
            { value: "preview", label: t("sj.note.preview") },
          ]}
        />
      }
    >
      <form onSubmit={(event) => void save(event)} className="space-y-3 p-3.5">
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        ) : null}
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,16rem)]">
          <FormRow label={t("sj.note.fieldTitle")} htmlFor="note-title">
            <Input
              id="note-title"
              value={title}
              maxLength={TITLE_MAX}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={t("sj.note.titlePlaceholder")}
              autoFocus
            />
          </FormRow>
          <FormRow label={t("sj.col.module")} htmlFor="note-module">
            <ModuleInput id="note-module" value={module} onChange={setModule} modules={modules} />
          </FormRow>
        </div>

        {view === "write" ? (
          <FormRow label={t("sj.note.fieldBody")} htmlFor="note-body" hint={t("sj.note.markdownHint")}>
            <Textarea
              id="note-body"
              rows={14}
              value={body}
              maxLength={BODY_MAX}
              onChange={(event) => setBody(event.target.value)}
              placeholder={t("sj.note.bodyPlaceholder")}
              className="font-mono text-[13px]"
            />
          </FormRow>
        ) : (
          <div
            aria-label={t("sj.note.preview")}
            className="min-h-[18rem] rounded border border-border bg-surface-2 p-4 text-[14px]"
          >
            {ready ? (
              <Markdown text={markdown} citations={[]} streaming={false} onCite={() => undefined} />
            ) : (
              <p className="text-muted">{t("sj.note.previewEmpty")}</p>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted">{t("sj.note.filename", { name: noteFilename(title) })}</p>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onCancel} disabled={busy}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" loading={busy} disabled={!ready} title={ready ? undefined : t("sj.note.needBoth")}>
              {t("sj.note.save")}
            </Button>
          </div>
        </div>
      </form>
    </Panel>
  );
}
