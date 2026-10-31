"use client";

import clsx from "clsx";
import { Check, ChevronsUpDown } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Popover } from "@/components/kit/popover";
import { setCourseCookie } from "@/components/shell/course";
import { useT } from "@/i18n/client";
import type { Subject } from "@/lib/types";

/** Picks the course the whole workspace is about: the dashboard shows it, and a new chat starts
 *  inside it. "All courses" clears the choice. */
export function CourseSwitcher({ subjects, currentId }: { subjects: Subject[]; currentId: string | null }) {
  const t = useT();
  const router = useRouter();
  const current = subjects.find((subject) => subject.id === currentId) ?? null;

  function choose(id: string | null, close: () => void) {
    setCourseCookie(id);
    close();
    router.refresh();
  }

  return (
    <Popover
      align="start"
      label={t("course.label")}
      panelClassName="w-64 p-1"
      trigger={({ open, toggle, id }) => (
        <button
          type="button"
          data-popover-trigger
          onClick={toggle}
          aria-expanded={open}
          aria-controls={open ? id : undefined}
          className="flex w-full items-center gap-2 rounded-xl border border-border bg-surface-2 px-3 py-2 text-left transition-colors hover:border-border-strong"
        >
          <span className="min-w-0 flex-1">
            <span className="block text-[10px] font-semibold uppercase tracking-wider text-faint">{t("course.label")}</span>
            <span className="block truncate text-sm font-medium">{current ? current.name : t("course.none")}</span>
          </span>
          <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-faint" aria-hidden />
        </button>
      )}
    >
      {(close) => (
        <div className="max-h-80 overflow-y-auto">
          <button
            type="button"
            onClick={() => choose(null, close)}
            className="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-sm hover:bg-surface-3"
          >
            <span className="min-w-0 flex-1 truncate text-muted">{t("course.none")}</span>
            {!current ? <Check className="h-3.5 w-3.5 text-brand" aria-hidden /> : null}
          </button>
          {subjects.map((subject) => (
            <button
              key={subject.id}
              type="button"
              onClick={() => choose(subject.id, close)}
              className="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-sm hover:bg-surface-3"
            >
              <span className="min-w-0 flex-1">
                <span className={clsx("block truncate", subject.id === currentId && "font-medium")}>{subject.name}</span>
                {subject.course_code ? <span className="block truncate text-xs text-faint">{subject.course_code}</span> : null}
              </span>
              {subject.id === currentId ? <Check className="h-3.5 w-3.5 shrink-0 text-brand" aria-hidden /> : null}
            </button>
          ))}
          <div className="mt-1 border-t border-border pt-1">
            <Link href="/subjects?new=1" onClick={close} className="block rounded px-2.5 py-1.5 text-sm text-brand hover:bg-surface-3">
              {t("course.add")}
            </Link>
          </div>
        </div>
      )}
    </Popover>
  );
}
