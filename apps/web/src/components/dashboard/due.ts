import type { Tone } from "@/components/kit/badge";
import type { TFunction } from "@/i18n/translate";

/** "Due today", "Due in 3 days", "2 days overdue" in the student's language. */
export function dueText(t: TFunction, days: number): string {
  if (days < 0) return t("dashboard.overdue", { days: -days });
  if (days === 0) return t("dashboard.dueToday");
  if (days === 1) return t("dashboard.dueTomorrow");
  return t("dashboard.dueIn", { days });
}

export function dueTone(days: number): Tone {
  if (days < 0) return "danger";
  if (days <= 2) return "warning";
  return "neutral";
}
