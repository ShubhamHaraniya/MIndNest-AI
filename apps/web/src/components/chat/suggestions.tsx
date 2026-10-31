"use client";

import { CornerDownRight, HelpCircle } from "lucide-react";

import type { Turn } from "@/components/chat/turns";
import { useT } from "@/i18n/client";

/** What the answer proposes next. Follow-up questions are one tap to ask; a clarifying question
 *  comes with its options (the student can also just type something else). Both send ordinary
 *  chat messages, so nothing happens that the student did not choose. */
export function Suggestions({
  turn,
  disabled,
  onAsk,
}: {
  turn: Turn;
  disabled: boolean;
  onAsk: (text: string) => void;
}) {
  const t = useT();
  if (turn.choices === null && turn.followups.length === 0) return null;

  return (
    <div className="mt-3 space-y-3">
      {turn.choices ? (
        <section aria-label={t("chx.choices")} className="glass-flat rounded-2xl p-3.5">
          <p className="flex items-start gap-2 text-sm font-medium">
            <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-brand" aria-hidden />
            {turn.choices.question}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {turn.choices.options.map((option) => (
              <button
                key={option}
                type="button"
                disabled={disabled}
                onClick={() => onAsk(option)}
                className="rounded-full border border-border-strong bg-surface-2/60 px-3.5 py-1.5 text-left text-[13px] transition-colors hover:border-primary hover:bg-primary-soft hover:text-brand disabled:opacity-50"
              >
                {option}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-faint">{t("chx.choices.hint")}</p>
        </section>
      ) : null}

      {turn.followups.length > 0 ? (
        <section aria-label={t("chx.followups")}>
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-faint rtl:tracking-normal">
            {t("chx.followups")}
          </h3>
          <ul className="space-y-px">
            {turn.followups.map((question) => (
              <li key={question}>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onAsk(question)}
                  className="flex w-full items-baseline gap-2 rounded-xl px-2 py-1.5 text-left text-[13px] hover:bg-surface-3/50 hover:text-brand disabled:opacity-50"
                >
                  <CornerDownRight className="h-3 w-3 shrink-0 translate-y-0.5 text-faint" aria-hidden />
                  <span className="min-w-0 flex-1">{question}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
