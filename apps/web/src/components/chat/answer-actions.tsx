"use client";

import clsx from "clsx";
import { Check, Copy, History, Loader2, RefreshCw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/kit/button";
import { Popover } from "@/components/kit/popover";
import type { Turn } from "@/components/chat/turns";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { FEEDBACK_REASONS, stripPartialTail } from "@/lib/chat";
import { formatDateTime } from "@/lib/format";
import type { AnswerFeedback, FeedbackReason } from "@/lib/types";

type Version = { id: string; text: string; created_at: string };

const ACTION =
  "flex h-7 items-center gap-1 rounded px-1.5 text-xs text-muted hover:bg-surface-2 hover:text-ink disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted";

/** What the student can do with a finished answer: copy it, ask again, rate it, and look at the
 *  answers it replaced. */
export function AnswerActions({
  turn,
  canRegenerate,
  busy,
  onRegenerate,
  onRate,
  onWithdraw,
}: {
  turn: Turn;
  /** Only the last answer of a conversation can be written again. */
  canRegenerate: boolean;
  busy: boolean;
  onRegenerate: () => void;
  onRate: (rating: AnswerFeedback["rating"], reason: FeedbackReason | null, comment: string) => Promise<void>;
  onWithdraw: () => Promise<void>;
}) {
  const t = useT();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(stripPartialTail(turn.text));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard access can be refused; nothing else to do.
    }
  }

  const rated = turn.feedback?.rating ?? null;
  const saved = turn.messageId !== null;

  return (
    <div className="mt-2 flex flex-wrap items-center gap-0.5">
      <button type="button" onClick={() => void copy()} className={ACTION}>
        {copied ? <Check className="h-3 w-3" aria-hidden /> : <Copy className="h-3 w-3" aria-hidden />}
        {copied ? t("chat.copied") : t("cw.copyAnswer")}
      </button>

      {canRegenerate ? (
        <button type="button" onClick={onRegenerate} disabled={busy} className={ACTION} title={t("chx.regenerate.hint")}>
          <RefreshCw className="h-3 w-3" aria-hidden />
          {t("chx.regenerate")}
        </button>
      ) : null}

      <span className="mx-1 h-4 w-px bg-border" aria-hidden />

      <button
        type="button"
        disabled={!saved || busy}
        aria-pressed={rated === "up"}
        aria-label={t("chx.rate.up")}
        title={t("chx.rate.up")}
        onClick={() => void (rated === "up" ? onWithdraw() : onRate("up", null, ""))}
        className={clsx(ACTION, rated === "up" && "bg-surface-2 text-success")}
      >
        <ThumbsUp className="h-3.5 w-3.5" aria-hidden />
      </button>

      <DownRating turn={turn} disabled={!saved || busy} onRate={onRate} onWithdraw={onWithdraw} />

      {turn.replaced && saved ? <EarlierVersions messageId={turn.messageId as string} /> : null}
    </div>
  );
}

/** The thumbs-down button: it opens a short form (why, and an optional note). */
function DownRating({
  turn,
  disabled,
  onRate,
  onWithdraw,
}: {
  turn: Turn;
  disabled: boolean;
  onRate: (rating: AnswerFeedback["rating"], reason: FeedbackReason | null, comment: string) => Promise<void>;
  onWithdraw: () => Promise<void>;
}) {
  const t = useT();
  const current = turn.feedback?.rating === "down" ? turn.feedback : null;
  const [reason, setReason] = useState<FeedbackReason | null>(current?.reason ?? null);
  const [comment, setComment] = useState("");
  const [working, setWorking] = useState(false);
  const [failed, setFailed] = useState(false);

  async function run(action: () => Promise<void>, close: () => void) {
    setWorking(true);
    setFailed(false);
    try {
      await action();
      close();
    } catch {
      setFailed(true);
    } finally {
      setWorking(false);
    }
  }

  return (
    <Popover
      label={t("chx.rate.down")}
      align="start"
      side="top"
      panelClassName="w-72 p-3"
      onOpenChange={(open) => {
        if (open) {
          setReason(current?.reason ?? null);
          setFailed(false);
        }
      }}
      trigger={({ toggle, open, id }) => (
        <button
          type="button"
          data-popover-trigger
          disabled={disabled}
          aria-expanded={open}
          aria-controls={open ? id : undefined}
          aria-pressed={current !== null}
          aria-label={t("chx.rate.down")}
          title={t("chx.rate.down")}
          onClick={toggle}
          className={clsx(ACTION, current && "bg-surface-2 text-danger")}
        >
          <ThumbsDown className="h-3.5 w-3.5" aria-hidden />
        </button>
      )}
    >
      {(close) => (
        <form
          className="space-y-3 text-xs"
          onSubmit={(event) => {
            event.preventDefault();
            void run(() => onRate("down", reason, comment.trim()), close);
          }}
        >
          <fieldset>
            <legend className="mb-1.5 font-medium text-ink">{t("chx.rate.why")}</legend>
            <div className="space-y-1">
              {FEEDBACK_REASONS.map((option) => (
                <label key={option.value} className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-surface-2">
                  <input
                    type="radio"
                    name={`reason-${turn.key}`}
                    checked={reason === option.value}
                    onChange={() => setReason(option.value)}
                    className="accent-primary"
                  />
                  {t(option.key)}
                </label>
              ))}
            </div>
          </fieldset>
          <label className="block">
            <span className="mb-1 block text-muted">{t("chx.rate.note")}</span>
            <textarea
              value={comment}
              maxLength={500}
              rows={2}
              onChange={(event) => setComment(event.target.value)}
              className="w-full resize-none rounded border border-border bg-surface px-2 py-1 text-[13px] text-ink focus:border-primary focus:outline-none"
            />
          </label>
          {failed ? <p className="text-danger">{t("chx.rate.failed")}</p> : null}
          <div className="flex items-center justify-between gap-2">
            {current ? (
              <button
                type="button"
                disabled={working}
                onClick={() => void run(onWithdraw, close)}
                className="text-muted underline hover:text-ink"
              >
                {t("chx.rate.remove")}
              </button>
            ) : (
              <span />
            )}
            <Button type="submit" size="sm" loading={working}>
              {t("chx.rate.send")}
            </Button>
          </div>
        </form>
      )}
    </Popover>
  );
}

/** The answers this one replaced, newest first. */
function EarlierVersions({ messageId }: { messageId: string }) {
  const t = useT();
  const locale = useLocale();
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  async function load() {
    setFailed(false);
    try {
      setVersions(await api<Version[]>(`/messages/${messageId}/versions`));
    } catch {
      setFailed(true);
    }
  }

  return (
    <Popover
      label={t("chx.versions")}
      align="start"
      side="top"
      panelClassName="w-[min(26rem,86vw)] p-3"
      onOpenChange={(isOpen) => {
        if (isOpen) void load();
      }}
      trigger={({ toggle, open: isOpen, id }) => (
        <button
          type="button"
          data-popover-trigger
          aria-expanded={isOpen}
          aria-controls={isOpen ? id : undefined}
          onClick={toggle}
          className={ACTION}
        >
          <History className="h-3 w-3" aria-hidden />
          {t("chx.versions")}
        </button>
      )}
    >
      <div className="text-xs">
        <p className="mb-2 font-medium text-ink">{t("chx.versions.title")}</p>
        {failed ? (
          <p className="text-danger">{t("chx.versions.failed")}</p>
        ) : versions === null ? (
          <p className="flex items-center gap-2 text-muted">
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            {t("common.loading")}
          </p>
        ) : versions.length === 0 ? (
          <p className="text-muted">{t("chx.versions.none")}</p>
        ) : (
          <ol className="max-h-72 space-y-2 overflow-y-auto">
            {versions.map((version) => (
              <li key={version.id} className="border-l-2 border-border pl-2">
                <p className="text-faint">{formatDateTime(version.created_at, locale)}</p>
                <p className="mt-0.5 whitespace-pre-wrap text-[13px] leading-snug text-ink">
                  {open === version.id || version.text.length <= 320 ? version.text : `${version.text.slice(0, 320)}…`}
                </p>
                {version.text.length > 320 ? (
                  <button
                    type="button"
                    onClick={() => setOpen(open === version.id ? null : version.id)}
                    className="mt-0.5 text-brand underline"
                  >
                    {open === version.id ? t("chx.versions.less") : t("chx.versions.more")}
                  </button>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </div>
    </Popover>
  );
}
