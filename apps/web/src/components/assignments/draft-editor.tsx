"use client";

import clsx from "clsx";
import { BookmarkPlus, MessageSquareText } from "lucide-react";
import { useLayoutEffect, useRef, useState, type FormEvent } from "react";

import type { SaveStatus } from "@/components/assignments/use-autosave";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/kit/button";
import { Input, Segmented } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { Popover } from "@/components/kit/popover";
import { useLocale, useT } from "@/i18n/client";
import { MAX_DRAFT_CHARS, countWords } from "@/lib/assignments";
import { bcp47 } from "@/lib/format";

type Mode = "write" | "preview";

/** The student's own writing: a plain text area with autosave and a Markdown preview. The text
 *  is theirs; nothing here rewrites it. */
export function DraftEditor({
  value,
  onChange,
  status,
  savedAt,
  onSaveNow,
  onSaveVersion,
  onFeedback,
  feedbackBusy,
}: {
  value: string;
  onChange: (text: string) => void;
  status: SaveStatus;
  savedAt: Date | null;
  onSaveNow: () => void;
  onSaveVersion: (note: string) => Promise<boolean>;
  onFeedback: () => void;
  feedbackBusy: boolean;
}) {
  const t = useT();
  const locale = useLocale();
  const [mode, setMode] = useState<Mode>("write");
  const area = useRef<HTMLTextAreaElement>(null);
  const words = countWords(value);

  // The text area grows with the writing, so the page scrolls rather than the box.
  useLayoutEffect(() => {
    const element = area.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.max(element.scrollHeight, 400)}px`;
  }, [value, mode]);

  const saved = savedAt
    ? new Intl.DateTimeFormat(bcp47(locale), { hour: "2-digit", minute: "2-digit" }).format(savedAt)
    : null;

  return (
    <Panel
      id="draft"
      title={t("assign.detail.draft")}
      action={
        <Segmented<Mode>
          label={t("asw.draft.mode")}
          value={mode}
          onChange={setMode}
          options={[
            { value: "write", label: t("asw.draft.write") },
            { value: "preview", label: t("asw.draft.preview") },
          ]}
        />
      }
      footer={
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <p className="tabular flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>{t("asw.draft.words", { count: words })}</span>
            <span className={value.length > MAX_DRAFT_CHARS * 0.95 ? "text-warning" : undefined}>
              {value.length.toLocaleString(bcp47(locale))} / {MAX_DRAFT_CHARS.toLocaleString(bcp47(locale))}
            </span>
            <span
              role="status"
              className={clsx(status === "error" && "font-medium text-danger", status === "dirty" && "text-warning")}
            >
              {status === "saving"
                ? t("asw.draft.saving")
                : status === "dirty"
                  ? t("asw.draft.dirty")
                  : status === "error"
                    ? t("asw.draft.error")
                    : saved
                      ? t("asw.draft.savedAt", { time: saved })
                      : t("asw.draft.saved")}
            </span>
            {status === "error" ? (
              <button type="button" onClick={onSaveNow} className="font-medium text-brand underline-offset-2 hover:underline">
                {t("common.retry")}
              </button>
            ) : null}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <VersionPopover onSave={onSaveVersion} disabled={value.trim() === ""} />
            <Button
              size="sm"
              onClick={onFeedback}
              loading={feedbackBusy}
              disabled={value.trim() === ""}
              title={value.trim() === "" ? t("assign.detail.needDraft") : undefined}
            >
              <MessageSquareText className="h-3.5 w-3.5" aria-hidden />
              {t("assign.kind.feedback")}
            </Button>
          </div>
        </div>
      }
    >
      {mode === "write" ? (
        <textarea
          id="assignment-draft"
          ref={area}
          value={value}
          maxLength={MAX_DRAFT_CHARS}
          onChange={(event) => onChange(event.target.value)}
          onBlur={onSaveNow}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
              event.preventDefault();
              onSaveNow();
            }
          }}
          aria-label={t("assign.detail.draft")}
          placeholder={t("asw.draft.placeholder")}
          spellCheck
          className="block w-full resize-none border-0 bg-transparent px-5 py-4 font-display text-[16.5px] leading-8 text-ink placeholder:text-faint focus:outline-none"
          style={{ minHeight: 400 }}
        />
      ) : value.trim() === "" ? (
        <p className="px-4 py-6 text-sm text-muted">{t("asw.draft.previewEmpty")}</p>
      ) : (
        <div className="min-h-[25rem] px-5 py-4 font-display text-[16.5px] leading-8">
          <Markdown text={value} citations={[]} streaming={false} onCite={() => undefined} />
        </div>
      )}
    </Panel>
  );
}

/** Pin the draft as it is now, with a short note ("first full draft"). */
function VersionPopover({ onSave, disabled }: { onSave: (note: string) => Promise<boolean>; disabled: boolean }) {
  const t = useT();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <Popover
      label={t("asw.version.title")}
      side="top"
      panelClassName="w-72 p-3"
      trigger={({ open, toggle, id }) => (
        <Button
          variant="secondary"
          size="sm"
          data-popover-trigger
          aria-expanded={open}
          aria-controls={open ? id : undefined}
          onClick={toggle}
          disabled={disabled}
          title={disabled ? t("assign.detail.needDraft") : undefined}
        >
          <BookmarkPlus className="h-3.5 w-3.5" aria-hidden />
          {t("asw.version.button")}
        </Button>
      )}
    >
      {(close) => (
        <form
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            setBusy(true);
            void onSave(note.trim()).then((ok) => {
              setBusy(false);
              if (ok) {
                setNote("");
                close();
              }
            });
          }}
          className="space-y-2.5"
        >
          <p className="text-[13px] font-medium">{t("asw.version.title")}</p>
          <p className="text-xs text-muted">{t("asw.version.hint")}</p>
          <Input
            autoFocus
            value={note}
            maxLength={200}
            onChange={(event) => setNote(event.target.value)}
            placeholder={t("asw.version.placeholder")}
            aria-label={t("asw.version.note")}
          />
          <div className="flex justify-end">
            <Button type="submit" size="sm" loading={busy}>
              {t("asw.version.save")}
            </Button>
          </div>
        </form>
      )}
    </Popover>
  );
}
