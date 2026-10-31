"use client";

import clsx from "clsx";
import { FileText, Loader2, Sparkles } from "lucide-react";
import { memo, useCallback, useMemo } from "react";

import { ChatCards, type DecideFn } from "@/components/chat-cards";
import { StepsTimeline } from "@/components/chat-steps";
import { AnswerActions } from "@/components/chat/answer-actions";
import { Suggestions } from "@/components/chat/suggestions";
import { citedNumbers, type Turn } from "@/components/chat/turns";
import { Markdown } from "@/components/markdown";
import { Alert } from "@/components/ui";
import { useT } from "@/i18n/client";
import { stripPartialTail } from "@/lib/chat";
import { llmErrorText } from "@/lib/errors";
import type { AnswerFeedback, FeedbackReason } from "@/lib/types";

/** What the student asked: a lit emerald bubble on the right. */
export function UserMessage({ text }: { text: string }) {
  const t = useT();
  return (
    <div className="ml-auto max-w-[88%] rounded-3xl rounded-br-md bg-gradient-to-br from-primary to-primary-hover px-5 py-3 text-on-primary shadow-glow ring-1 ring-inset ring-white/20 sm:max-w-[80%]">
      <p className="sr-only">{t("cw.you")}</p>
      <p className="whitespace-pre-wrap text-[15px] leading-relaxed">{text}</p>
    </div>
  );
}

// Memoised so typing in the message box does not re-render (and re-parse) every old answer.
export const AssistantMessage = memo(function AssistantMessage({
  turn,
  activeSource,
  onCite,
  onDecide,
  busy,
  isLast,
  onRegenerate,
  onAsk,
  onRate,
  onWithdraw,
}: {
  turn: Turn;
  /** The source number shown in the side panel for this answer, if any. */
  activeSource: number | null;
  onCite: (turnKey: string, n: number) => void;
  onDecide: DecideFn;
  busy: boolean;
  /** True for the newest answer: only it can be written again, and only it shows suggestions. */
  isLast: boolean;
  onRegenerate: () => void;
  onAsk: (text: string) => void;
  onRate: (
    turnKey: string,
    rating: AnswerFeedback["rating"],
    reason: FeedbackReason | null,
    comment: string,
  ) => Promise<void>;
  onWithdraw: (turnKey: string) => Promise<void>;
}) {
  const t = useT();
  // A follow-up / choice block at the end is shown as buttons, never as text.
  const shown = useMemo(() => stripPartialTail(turn.text), [turn.text]);
  const cited = useMemo(() => citedNumbers(shown, turn.sources), [shown, turn.sources]);
  const numbers = useMemo(() => turn.sources.map((source) => source.n), [turn.sources]);
  const cite = useCallback((n: number) => onCite(turn.key, n), [onCite, turn.key]);
  const finished = !turn.streaming && !turn.error && !turn.stopped && turn.text.length > 0;
  const searching = turn.steps.some((step) => step.tool === "search_materials" && step.status === "running");
  // Only answers that could have used the student's notes explain when none were found.
  const usedStudy = turn.route === null || turn.route.agents.includes("study");

  const rate = useCallback(
    (rating: AnswerFeedback["rating"], reason: FeedbackReason | null, comment: string) =>
      onRate(turn.key, rating, reason, comment),
    [onRate, turn.key],
  );
  const withdraw = useCallback(() => onWithdraw(turn.key), [onWithdraw, turn.key]);

  return (
    <div className="max-w-full">
      <p className="mb-2 flex items-center gap-2 text-xs font-semibold text-muted">
        <span
          className={clsx(
            "flex h-7 w-7 items-center justify-center rounded-xl bg-primary-soft text-brand ring-1 ring-primary/25",
            turn.streaming && "animate-glow-pulse shadow-glow",
          )}
        >
          <Sparkles className="h-3.5 w-3.5" aria-hidden />
        </span>
        {t("cw.assistant")}
      </p>
      <div className={clsx("glass-flat rounded-3xl rounded-tl-md px-5 py-4 transition-shadow", turn.streaming && "border-primary/30 shadow-glow")}>
      <StepsTimeline steps={turn.steps} route={turn.route} live={turn.streaming} />
      {shown ? (
        <Markdown text={shown} citations={numbers} streaming={turn.streaming} onCite={cite} />
      ) : turn.streaming ? (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {searching ? t("chat.searching") : t("chat.thinking")}
        </p>
      ) : null}

      {turn.error ? (
        <div className="mt-3">
          <Alert>{llmErrorText(turn.error, t)}</Alert>
        </div>
      ) : null}
      {turn.stopped ? <p className="mt-2 text-xs text-muted">{t("chat.stopped")}</p> : null}
      {turn.cleaned ? <p className="mt-2 text-xs text-warning">{t("chat.safety.cleaned")}</p> : null}
      </div>

      {cited.length > 0 ? (
        <section aria-label={t("cw.sources")} className="mt-3">
          <h3 className="mb-1.5 ps-1 text-[11px] font-semibold uppercase tracking-wide text-faint rtl:tracking-normal">
            {t("cw.sources")}
          </h3>
          <ol className="flex flex-wrap gap-2">
            {cited.map((n) => {
              const source = turn.sources.find((s) => s.n === n);
              if (!source) return null;
              const open = activeSource === n;
              return (
                <li key={n} className="max-w-full">
                  <button
                    type="button"
                    onClick={() => cite(n)}
                    aria-pressed={open}
                    title={t("cw.inspect")}
                    className={clsx(
                      "inline-flex max-w-full items-center gap-2 rounded-full border px-3 py-1.5 text-start text-xs transition-colors",
                      open
                        ? "border-primary/60 bg-primary-soft text-brand shadow-glow"
                        : "border-border bg-surface-2/60 hover:border-primary/40 hover:bg-primary-soft",
                    )}
                  >
                    <span className="font-semibold text-brand">[{n}]</span>
                    <FileText className="h-3 w-3 shrink-0 text-faint" aria-hidden />
                    <span className="min-w-0 max-w-[16rem] truncate">{source.filename}</span>
                    {source.page !== null ? <span className="shrink-0 text-muted">{t("chat.page", { n: source.page })}</span> : null}
                    <span className="sr-only">{t("cw.inspect")}</span>
                  </button>
                </li>
              );
            })}
          </ol>
        </section>
      ) : null}

      {turn.cards.length > 0 ? <ChatCards cards={turn.cards} onDecide={onDecide} busy={busy} /> : null}

      {finished && usedStudy && turn.sources.length === 0 ? (
        <p className="mt-3 text-xs text-muted">{t("chat.noSources")}</p>
      ) : null}
      {turn.degraded ? <p className="mt-2 text-xs text-warning">{t("chat.degraded")}</p> : null}

      {finished ? (
        <AnswerActions
          turn={turn}
          canRegenerate={isLast}
          busy={busy}
          onRegenerate={onRegenerate}
          onRate={rate}
          onWithdraw={withdraw}
        />
      ) : null}
      {finished && isLast ? <Suggestions turn={turn} disabled={busy} onAsk={onAsk} /> : null}
    </div>
  );
});
