"use client";

import { AlertTriangle, CalendarClock, ChevronRight, FileUp, ListChecks, RefreshCw, Repeat } from "lucide-react";
import Link from "next/link";
import type { ComponentType, ReactNode } from "react";

import { Panel } from "@/components/kit/panel";
import { Skeleton } from "@/components/kit/skeleton";
import { useT } from "@/i18n/client";
import type { TFunction } from "@/i18n/translate";
import { percent } from "@/lib/format";

import { dueText } from "./bits";
import type { CourseAnalytics, Recommendation } from "./model";
import type { Resource } from "./use-resource";

type Target = { href: string } | { onClick: () => void };

const ICONS: Record<Recommendation["kind"], ComponentType<{ className?: string; "aria-hidden"?: boolean }>> = {
  deadline: CalendarClock,
  revision_due: Repeat,
  weak_topic: AlertTriangle,
  retry_failed: RefreshCw,
  first_quiz: ListChecks,
  upload_first: FileUp,
};

function describe(t: TFunction, item: Recommendation): string {
  const p = item.params;
  switch (item.kind) {
    case "deadline":
      return t(p.what === "exam" ? "sj.rec.exam" : "sj.rec.assignment", {
        label: item.label ?? "",
        when: dueText(t, Number(p.days)),
      });
    case "revision_due":
      return t("sj.rec.revision", { count: Number(p.count) });
    case "weak_topic":
      return t("sj.rec.weak", { label: item.label ?? "", accuracy: percent(Number(p.accuracy)) });
    case "retry_failed":
      return t("sj.rec.failed", { count: Number(p.count) });
    case "first_quiz":
      return t("sj.rec.firstQuiz");
    case "upload_first":
      return t("sj.rec.upload");
  }
}

/** The few things worth doing next in this course, each from something measured (a deadline, a
 *  weak file, cards due). With nothing measured the list is empty and says so. */
export function RecommendedNext({
  analytics,
  subjectId,
  onOpenDoc,
  onUpload,
  onShowMaterials,
}: {
  analytics: Resource<CourseAnalytics>;
  subjectId: string;
  onOpenDoc: (id: string) => void;
  onUpload: () => void;
  onShowMaterials: () => void;
}) {
  const t = useT();
  const items = analytics.data?.recommendations ?? [];

  function target(item: Recommendation): Target {
    switch (item.kind) {
      case "deadline":
        return item.params.what === "exam" ? { href: "/planner" } : { href: `/assignments/${item.ref_id}` };
      case "revision_due":
        return { href: "/quizzes" };
      case "weak_topic":
        return item.ref_id ? { onClick: () => onOpenDoc(item.ref_id as string) } : { href: `/quizzes?subject=${subjectId}` };
      case "retry_failed":
        return { onClick: onShowMaterials };
      case "first_quiz":
        return { href: `/quizzes?subject=${subjectId}` };
      case "upload_first":
        return { onClick: onUpload };
    }
  }

  let body: ReactNode;
  if (analytics.error && !analytics.data) {
    body = <p className="px-3.5 py-4 text-sm text-muted">{t("sj.rec.unavailable")}</p>;
  } else if (analytics.loading || !analytics.data) {
    body = (
      <div className="space-y-3 p-3.5" aria-hidden>
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    );
  } else if (items.length === 0) {
    body = <p className="px-3.5 py-4 text-sm text-muted">{t("sj.rec.none")}</p>;
  } else {
    body = (
      <ul className="divide-y divide-border">
        {items.map((item) => {
          const Icon = ICONS[item.kind];
          const to = target(item);
          const inner = (
            <>
              <Icon className="h-4 w-4 shrink-0 text-faint" aria-hidden />
              <span className="min-w-0 flex-1 text-[13px]">{describe(t, item)}</span>
              <ChevronRight className="h-3.5 w-3.5 shrink-0 text-faint rtl:rotate-180" aria-hidden />
            </>
          );
          const row = "flex w-full items-center gap-2.5 px-3.5 py-2 text-left hover:bg-surface-2";
          return (
            <li key={`${item.kind}-${item.ref_id ?? item.label ?? ""}`}>
              {"href" in to ? (
                <Link href={to.href} className={row}>
                  {inner}
                </Link>
              ) : (
                <button type="button" onClick={to.onClick} className={row}>
                  {inner}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <Panel id="recommended" title={t("sj.rec.title")} description={t("sj.rec.help")}>
      {body}
    </Panel>
  );
}
