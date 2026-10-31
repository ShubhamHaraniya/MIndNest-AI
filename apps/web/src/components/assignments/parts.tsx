"use client";

import { Badge, type Tone } from "@/components/kit/badge";
import { useT } from "@/i18n/client";
import type { TFunction } from "@/i18n/translate";
import { daysLeft, dueTone } from "@/lib/assignments";
import { bcp47 } from "@/lib/format";
import type { AssignmentStatus } from "@/lib/types";

const STATUS_TONE: Record<AssignmentStatus, Tone> = { todo: "neutral", in_progress: "info", done: "success" };

export function StatusBadge({ status }: { status: AssignmentStatus }) {
  const t = useT();
  return <Badge tone={STATUS_TONE[status]}>{t(`assign.status.${status}`)}</Badge>;
}

/** "3 d overdue", "Today", "Tomorrow", "In 5 days". */
export function dueWords(t: TFunction, days: number): string {
  if (days < 0) return t("dashboard.overdue", { days: -days });
  if (days === 0) return t("dashboard.dueToday");
  if (days === 1) return t("dashboard.dueTomorrow");
  return t("dashboard.dueIn", { days });
}

/** The due date with how far away it is; the tag turns amber when it is near and red when it has
 *  passed, and says so in words as well. A finished assignment is never flagged. */
export function DueCell({
  dueAt,
  status,
  locale,
  inline = false,
}: {
  dueAt: string | null;
  status: AssignmentStatus;
  locale: string;
  inline?: boolean;
}) {
  const t = useT();
  if (!dueAt) return <span className="text-faint">{t("assign.due.none")}</span>;
  const days = daysLeft(dueAt) ?? 0;
  const done = status === "done";
  const date = new Intl.DateTimeFormat(bcp47(locale), { day: "numeric", month: "short", year: "numeric" }).format(new Date(dueAt));
  return (
    <span className={inline ? "inline-flex flex-wrap items-center gap-x-2 gap-y-1" : "flex flex-col items-start gap-0.5"}>
      <span className="tabular whitespace-nowrap">{date}</span>
      {done ? null : <Badge tone={dueTone(days, false)}>{dueWords(t, days)}</Badge>}
    </span>
  );
}
