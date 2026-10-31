"use client";

import { Archive, ArchiveRestore, Crosshair, FileText, ListChecks, MessageSquare, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/kit/badge";
import { AnimatedRing } from "@/components/motion/ring";
import { IconButton, dueText, dueTone } from "@/components/subjects/bits";
import type { CourseFigures } from "@/components/subjects/model";
import { useLocale, useT } from "@/i18n/client";
import { percent, relativeTime } from "@/lib/format";

/** A stable colour for a course, from the five chart colours, so the same course always looks the same. */
export function hueOf(id: string): number {
  let sum = 0;
  for (const char of id) sum = (sum + char.charCodeAt(0)) % 5;
  return sum + 1;
}

/** One course as a card: a coloured initial, how much of it is readable by the AI, the next exam,
 *  and quick actions. The whole card opens the course; the small buttons do not. */
export function CourseCard({
  course,
  current,
  onMakeCurrent,
  onEdit,
  onArchive,
  onDelete,
}: {
  course: CourseFigures;
  current: boolean;
  onMakeCurrent: () => void;
  onEdit: () => void;
  onArchive: () => void;
  onDelete: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const hue = hueOf(course.id);
  const ratio = course.documents > 0 ? course.documents_ready / course.documents : 0;
  const meta = [course.course_code, course.semester].filter(Boolean).join(" · ");

  return (
    <article className="card-hover spot group relative flex flex-col overflow-hidden rounded-card border border-border bg-surface p-5 shadow-card">
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-28"
        style={{ background: `radial-gradient(20rem 7rem at 15% 0%, color-mix(in srgb, var(--chart-${hue}) 26%, transparent), transparent 70%)` }}
      />
      <Link href={`/subjects/${course.id}`} className="absolute inset-0 z-0 rounded-card" aria-label={course.name} />
      <div className="pointer-events-none relative z-10 flex items-start gap-3">
        <span
          aria-hidden
          className="font-display flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-lg"
          style={{
            color: `var(--chart-${hue})`,
            background: `color-mix(in srgb, var(--chart-${hue}) 14%, var(--surface))`,
          }}
        >
          {course.name.trim().charAt(0).toUpperCase() || "?"}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[15px] font-semibold leading-5" title={course.name}>
            {course.name}
          </h3>
          <p className="mt-0.5 truncate text-xs text-muted">{meta || t("sj.list.noCode")}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {current ? <Badge tone="brand">{t("sj.list.current")}</Badge> : null}
          {course.archived_at ? <Badge>{t("subjects.archivedBadge")}</Badge> : null}
        </div>
      </div>

      <div className="pointer-events-none relative z-10 mt-4 flex items-center gap-4">
        <AnimatedRing
          value={ratio}
          size={68}
          stroke={6}
          label={t("cc.readable")}
          tone={course.documents_failed > 0 ? "warning" : "primary"}
        >
          <span className="tabular text-sm font-semibold">{Math.round(ratio * 100)}%</span>
        </AnimatedRing>
        <div className="min-w-0 text-xs">
          <p className="text-muted">{t("cc.readable")}</p>
          <p className="tabular mt-0.5 text-lg font-semibold leading-6" title={t("sj.list.readyOf", { ready: course.documents_ready, total: course.documents })}>
            {course.documents_ready}
            <span className="text-faint"> / {course.documents}</span>
          </p>
          {course.documents_failed > 0 ? (
            <p className="mt-0.5 text-warning">{t("sj.list.failed", { count: course.documents_failed })}</p>
          ) : course.documents_working > 0 ? (
            <p className="mt-0.5 text-info">{t("sj.list.reading", { count: course.documents_working })}</p>
          ) : null}
        </div>
      </div>

      <dl className="pointer-events-none relative z-10 mt-4 grid grid-cols-3 gap-2 text-center">
        {[
          { icon: FileText, label: t("sj.tab.papers"), value: String(course.past_papers) },
          { icon: ListChecks, label: t("sj.col.quizAverage"), value: course.quiz_attempts > 0 ? percent(course.quiz_average) : "—" },
          { icon: MessageSquare, label: t("wb.course.chats"), value: String(course.chats) },
        ].map(({ icon: Icon, label, value }) => (
          <div key={label} className="glass-flat rounded-xl px-2 py-2">
            <dt className="flex items-center justify-center gap-1 truncate text-[11px] text-muted">
              <Icon className="h-3 w-3 shrink-0" aria-hidden />
              <span className="truncate">{label}</span>
            </dt>
            <dd className="tabular mt-0.5 text-sm font-semibold">{value}</dd>
          </div>
        ))}
      </dl>

      <div className="pointer-events-none relative z-10 mt-4 flex min-h-6 items-center justify-between gap-2 text-xs">
        {course.next_exam_title && course.next_exam_days !== null ? (
          <span className="flex min-w-0 items-center gap-1.5">
            <Badge tone={dueTone(course.next_exam_days)} className="shrink-0">
              {dueText(t, course.next_exam_days)}
            </Badge>
            <span className="truncate text-muted" title={course.next_exam_title}>
              {course.next_exam_title}
            </span>
          </span>
        ) : (
          <span className="truncate text-faint">
            {course.last_activity_at ? t("wb.course.lastActive", { when: relativeTime(course.last_activity_at, locale) }) : t("wb.course.noExam")}
          </span>
        )}
      </div>

      <div className="relative z-10 mt-3 flex items-center justify-end gap-0.5 border-t border-border pt-3">
        {!course.archived_at && !current ? (
          <IconButton label={t("sj.list.makeCurrent")} onClick={onMakeCurrent}>
            <Crosshair className="h-3.5 w-3.5" aria-hidden />
          </IconButton>
        ) : null}
        <IconButton label={t("common.edit")} onClick={onEdit}>
          <Pencil className="h-3.5 w-3.5" aria-hidden />
        </IconButton>
        <IconButton label={course.archived_at ? t("subjects.unarchive") : t("subjects.archive")} onClick={onArchive}>
          {course.archived_at ? <ArchiveRestore className="h-3.5 w-3.5" aria-hidden /> : <Archive className="h-3.5 w-3.5" aria-hidden />}
        </IconButton>
        <IconButton label={t("common.delete")} danger onClick={onDelete}>
          <Trash2 className="h-3.5 w-3.5" aria-hidden />
        </IconButton>
      </div>
    </article>
  );
}
