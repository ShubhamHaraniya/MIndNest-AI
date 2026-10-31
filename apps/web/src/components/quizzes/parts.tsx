"use client";

import { Loader2 } from "lucide-react";
import { memo } from "react";

import { Badge, type Tone } from "@/components/kit/badge";
import { Markdown } from "@/components/markdown";
import { useT } from "@/i18n/client";
import type { QuizDisplayStatus, QuizStatus } from "@/lib/types";

const STATUS_TONE: Record<QuizStatus, Tone> = {
  queued: "neutral",
  generating: "info",
  ready: "success",
  failed: "danger",
};

/** Where a quiz is in being written: waiting, writing, ready or failed. */
export function QuizStatusBadge({ status }: { status: QuizStatus }) {
  const t = useT();
  return (
    <Badge tone={STATUS_TONE[status]}>
      {status === "generating" || status === "queued" ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : null}
      {t(`quiz.status.${status}`)}
    </Badge>
  );
}

const DISPLAY_TONE: Record<QuizDisplayStatus, Tone> = {
  ready: "success",
  in_progress: "warning",
  completed: "brand",
  archived: "neutral",
  preparing: "info",
  failed: "danger",
};

/** The status every quiz screen shows: Ready, In progress, Completed or Archived (or Preparing /
 *  Failed while it is being written). */
export function QuizDisplayBadge({ status }: { status: QuizDisplayStatus }) {
  const t = useT();
  return (
    <Badge tone={DISPLAY_TONE[status]}>
      {status === "preparing" ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : null}
      {t(`qzx.st.${status}`)}
    </Badge>
  );
}

const noCite = () => {};
const NO_CITATIONS: number[] = [];

/** A question, option or explanation. Maths, code and tables render; there are no citations. */
export const QuizMarkdown = memo(function QuizMarkdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={className}>
      <Markdown text={text} citations={NO_CITATIONS} streaming={false} onCite={noCite} />
    </div>
  );
});

/** Class for markdown that sits inside a row or a button: no outer margins, body-sized text. */
export const INLINE_MD = "[&_.md-body]:text-[14px] [&_.md-body]:leading-6 [&_.md-body_p]:my-0";
