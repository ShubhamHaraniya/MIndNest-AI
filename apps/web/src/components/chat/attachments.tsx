"use client";

import { AlertCircle, CheckCircle2, FileImage, FileText, Loader2, X } from "lucide-react";

import { useT } from "@/i18n/client";
import { attachmentFailure, fileSize } from "@/lib/chat";
import type { ChatAttachment } from "@/lib/types";

/** The files attached to this conversation, with whether their text has been read yet. */
export function AttachmentChips({
  items,
  onRemove,
  disabled,
}: {
  items: ChatAttachment[];
  onRemove: (attachment: ChatAttachment) => void;
  disabled: boolean;
}) {
  const t = useT();
  if (items.length === 0) return null;
  return (
    <ul aria-label={t("chx.attach.list")} className="flex flex-wrap gap-1.5 px-2 pt-2">
      {items.map((item) => {
        const Icon = item.kind === "image" ? FileImage : FileText;
        const working = item.status === "uploaded" || item.status === "processing";
        return (
          <li
            key={item.id}
            className="glass-flat flex max-w-full items-center gap-1.5 rounded-full py-1 pl-2.5 pr-1.5 text-xs"
          >
            <Icon className="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden />
            <span className="min-w-0 max-w-[12rem] truncate font-medium" title={item.filename}>
              {item.filename}
            </span>
            <span className="shrink-0 text-faint">{fileSize(item.size_bytes)}</span>
            {working ? (
              <span className="flex shrink-0 items-center gap-1 text-muted">
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                {t("chx.attach.reading")}
              </span>
            ) : item.status === "ready" ? (
              <span className="flex shrink-0 items-center gap-1 text-success">
                <CheckCircle2 className="h-3 w-3" aria-hidden />
                {t("chx.attach.ready")}
              </span>
            ) : (
              <span className="flex shrink-0 items-center gap-1 text-danger" title={t(attachmentFailure(item.error))}>
                <AlertCircle className="h-3 w-3" aria-hidden />
                <span className="max-w-[14rem] truncate">{t(attachmentFailure(item.error))}</span>
              </span>
            )}
            <button
              type="button"
              onClick={() => onRemove(item)}
              disabled={disabled}
              aria-label={`${t("chx.attach.remove")}: ${item.filename}`}
              className="rounded p-0.5 text-muted hover:bg-surface-3 hover:text-danger disabled:opacity-40"
            >
              <X className="h-3 w-3" aria-hidden />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
