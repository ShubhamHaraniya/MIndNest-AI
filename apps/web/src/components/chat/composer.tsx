"use client";

import { ChevronDown, KeyRound, Paperclip, SendHorizonal, SlidersHorizontal, Square } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type DragEvent, type KeyboardEvent } from "react";

import { AttachmentChips } from "@/components/chat/attachments";
import { ScopePicker } from "@/components/chat/scope-picker";
import { Button } from "@/components/kit/button";
import { Popover } from "@/components/kit/popover";
import { useT } from "@/i18n/client";
import { ATTACH_ACCEPT, type ScopeValue } from "@/lib/chat";
import type { ChatAttachment, Provider, Subject } from "@/lib/types";

const MAX_ROWS_PX = 200;

/** The message box. The course the question is asked in and the model sit on a slim toolbar
 *  under the text, so the box itself stays the focus. */
export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  streaming,
  noKey,
  subjects,
  scope,
  onScope,
  attachments,
  onAttach,
  onRemoveAttachment,
  providers,
  providerId,
  onProvider,
  model,
  onModel,
  modelSuggestions,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  streaming: boolean;
  noKey: boolean;
  subjects: Subject[];
  scope: ScopeValue;
  onScope: (scope: ScopeValue) => void;
  attachments: ChatAttachment[];
  onAttach: (files: File[]) => void;
  onRemoveAttachment: (attachment: ChatAttachment) => void;
  providers: Provider[];
  providerId: string;
  onProvider: (id: string) => void;
  model: string;
  onModel: (name: string) => void;
  modelSuggestions: string[];
}) {
  const t = useT();
  const area = useRef<HTMLTextAreaElement>(null);
  const active = providers.find((p) => p.id === providerId);
  const picker = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  // Grow with the text, up to a limit, then scroll.
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_ROWS_PX)}px`;
  }, [value]);

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Do not send while an input method (Hindi, Gujarati) is still composing a word.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      onSend();
    }
  }

  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) onAttach(files);
  }

  if (noKey) {
    return (
      <div className="glass-flat rounded-2xl p-4 text-sm">
        <p className="flex items-center gap-2 font-semibold">
          <KeyRound className="h-4 w-4 text-brand" aria-hidden />
          {t("chat.noKeyTitle")}
        </p>
        <p className="mt-1 text-muted">{t("chat.noKeyBody")}</p>
        <Link
          href="/settings"
          className="mt-3 inline-flex h-8 items-center rounded bg-primary px-3 text-[13px] font-medium text-on-primary hover:bg-primary-hover"
        >
          {t("chat.goSettings")}
        </Link>
      </div>
    );
  }

  return (
    <div
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={drop}
      className={
        dragging
          ? "rounded-3xl border border-dashed border-primary bg-primary-soft"
          : "glass-strong rounded-3xl transition-shadow focus-within:border-primary/60 focus-within:ring-2 focus-within:ring-primary/25"
      }
    >
      <AttachmentChips items={attachments} onRemove={onRemoveAttachment} disabled={streaming} />
      <textarea
        ref={area}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        rows={2}
        maxLength={8000}
        placeholder={t("chat.placeholder")}
        aria-label={t("chat.placeholder")}
        className="block max-h-[200px] min-h-[3.25rem] w-full resize-none bg-transparent px-4 pb-1 pt-3.5 text-[15px] leading-6 placeholder:text-faint focus:outline-none"
      />
      <div className="flex items-center justify-between gap-2 px-1.5 pb-1.5">
        <div className="flex min-w-0 flex-wrap items-center gap-0.5">
          <input
            ref={picker}
            type="file"
            multiple
            accept={ATTACH_ACCEPT}
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              event.target.value = "";
              if (files.length > 0) onAttach(files);
            }}
          />
          <button
            type="button"
            onClick={() => picker.current?.click()}
            disabled={streaming}
            title={t("chx.attach.add")}
            aria-label={t("chx.attach.add")}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-muted hover:bg-surface-3 hover:text-ink disabled:opacity-60"
          >
            <Paperclip className="h-3.5 w-3.5" aria-hidden />
          </button>
          <ScopePicker subjects={subjects} scope={scope} disabled={streaming} onApply={onScope} />
          <Popover
            label={t("cw.composer.settings")}
            align="start"
            side="top"
            panelClassName="w-72 p-3"
            trigger={({ toggle, open, id }) => (
              <button
                type="button"
                data-popover-trigger
                aria-expanded={open}
                aria-controls={open ? id : undefined}
                onClick={toggle}
                title={t("chat.activeModel")}
                className="flex h-8 max-w-[14rem] items-center gap-1 rounded-lg px-2 text-xs text-muted hover:bg-surface-3 hover:text-ink"
              >
                <SlidersHorizontal className="h-3 w-3 shrink-0" aria-hidden />
                <span className="truncate">
                  {active?.label ?? "—"}
                  {model ? ` · ${model}` : ""}
                </span>
                <ChevronDown className="h-3 w-3 shrink-0" aria-hidden />
              </button>
            )}
          >
            <div className="space-y-3 text-xs">
              <label className="block">
                <span className="mb-1 block font-medium text-muted">{t("chat.provider")}</span>
                <select
                  value={providerId}
                  disabled={streaming}
                  onChange={(event) => onProvider(event.target.value)}
                  className="h-9 w-full rounded-lg border border-border bg-surface-2/60 px-2 text-[13px] text-ink"
                >
                  {providers.map((provider) => (
                    <option key={provider.id} value={provider.id}>
                      {provider.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block font-medium text-muted">{t("chat.model")}</span>
                <input
                  value={model}
                  disabled={streaming}
                  onChange={(event) => onModel(event.target.value)}
                  list="chat-model-suggestions"
                  className="h-9 w-full rounded-lg border border-border bg-surface-2/60 px-2 text-[13px] text-ink"
                />
                <datalist id="chat-model-suggestions">
                  {(modelSuggestions.length > 0 ? modelSuggestions : (active?.models ?? [])).map((name) => (
                    <option key={name} value={name} />
                  ))}
                </datalist>
              </label>
            </div>
          </Popover>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {streaming ? (
            <Button variant="secondary" onClick={onStop}>
              <Square className="h-3 w-3" aria-hidden />
              {t("chat.stop")}
            </Button>
          ) : (
            <Button onClick={onSend} disabled={!value.trim() || !providerId}>
              <SendHorizonal className="h-3.5 w-3.5" aria-hidden />
              {t("chat.send")}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
