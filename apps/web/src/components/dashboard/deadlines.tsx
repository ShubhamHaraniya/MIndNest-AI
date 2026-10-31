"use client";

import clsx from "clsx";
import { ClipboardList, GraduationCap } from "lucide-react";
import Link from "next/link";

import { dueText } from "@/components/dashboard/due";
import { Panel } from "@/components/kit/panel";
import { Stagger, StaggerItem } from "@/components/motion/reveal";
import { useLocale, useT } from "@/i18n/client";
import { formatDay } from "@/lib/format";
import type { DashboardData } from "@/lib/types";

function urgency(days: number): { ring: string; text: string; glow: boolean } {
  if (days < 0) return { ring: "border-danger/60 bg-danger-soft", text: "text-danger", glow: true };
  if (days <= 2) return { ring: "border-warning/60 bg-warning-soft", text: "text-warning", glow: true };
  if (days <= 7) return { ring: "border-info/50 bg-info-soft", text: "text-info", glow: false };
  return { ring: "border-border bg-surface-3/50", text: "text-muted", glow: false };
}

/** Exams and assignments as a countdown rail: the number of days in a ring that warms as it gets close. */
export function Deadlines({ items }: { items: DashboardData["deadlines"] }) {
  const t = useT();
  const locale = useLocale();
  const shown = items.slice(0, 5);
  return (
    <Panel id="deadlines" title={t("dashboard.deadlinesTitle")} description={t("dashboard.deadlinesBody")} className="h-full">
      {shown.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted">{t("dashboard.deadlinesEmpty")}</p>
      ) : (
        <Stagger as="ul" className="space-y-1 p-2">
          {shown.map((item) => {
            const tone = urgency(item.days_left);
            const Icon = item.kind === "exam" ? GraduationCap : ClipboardList;
            return (
              <StaggerItem as="li" key={`${item.kind}-${item.id}`}>
                <Link
                  href={item.kind === "assignment" ? `/assignments/${item.id}` : "/calendar"}
                  className="flex items-center gap-3.5 rounded-2xl px-2.5 py-2 transition-colors hover:bg-surface-3/50"
                >
                  <span
                    className={clsx(
                      "flex h-12 w-12 shrink-0 flex-col items-center justify-center rounded-full border",
                      tone.ring,
                      tone.text,
                      tone.glow && "shadow-glow",
                    )}
                  >
                    <span className="tabular font-display text-lg leading-5">{Math.abs(item.days_left)}</span>
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-medium">{item.title}</span>
                    <span className="flex items-center gap-1.5 truncate text-xs text-muted">
                      <Icon className="h-3 w-3 shrink-0" aria-hidden />
                      {t(item.kind === "exam" ? "dashboard.kindExam" : "dashboard.kindAssignment")}
                      {item.subject_name ? ` · ${item.subject_name}` : ""}
                    </span>
                  </span>
                  <span className="shrink-0 text-end">
                    <span className={clsx("block text-xs font-medium", tone.text)}>{dueText(t, item.days_left)}</span>
                    <span className="block text-[11px] text-faint">{formatDay(item.on, locale, { day: "numeric", month: "short" })}</span>
                  </span>
                </Link>
              </StaggerItem>
            );
          })}
        </Stagger>
      )}
    </Panel>
  );
}
