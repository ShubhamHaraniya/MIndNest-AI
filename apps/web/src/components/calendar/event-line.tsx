"use client";

import clsx from "clsx";
import { CloudOff, CloudUpload, Cloud, Pencil } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/kit/badge";
import { IconButton } from "@/components/subjects/bits";
import { useT } from "@/i18n/client";
import type { CalendarEvent, SyncState } from "@/lib/types";

import { KIND_STYLE, eventHref, eventLabel, isCancelled, timeRange } from "./model";

/** Whether an item is on Google Calendar. Waiting is only shown for the student's own events:
 *  every unsent study task would otherwise say it. */
export function SyncBadge({ state, kind }: { state: SyncState | null; kind: CalendarEvent["kind"] }) {
  const t = useT();
  if (state === null || (state === "pending" && kind !== "event")) return null;
  if (state === "synced") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] text-success" title={t("calx.sync.synced")}>
        <Cloud className="h-3 w-3" aria-hidden />
        {t("calx.sync.synced")}
      </span>
    );
  }
  if (state === "pending") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] text-muted" title={t("calx.sync.pendingHint")}>
        <CloudUpload className="h-3 w-3" aria-hidden />
        {t("calx.sync.pending")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-danger" title={t("calx.sync.failedHint")}>
      <CloudOff className="h-3 w-3" aria-hidden />
      {t("calx.sync.failed")}
    </span>
  );
}

/** One thing on the calendar, as a line: what kind, when, what, and where it is on Google. */
export function EventLine({
  event,
  onEdit,
  showKind = true,
}: {
  event: CalendarEvent;
  onEdit: (event: CalendarEvent) => void;
  showKind?: boolean;
}) {
  const t = useT();
  const label = eventLabel(event, t);
  const href = eventHref(event);
  const cancelled = isCancelled(event);
  const done = event.status === "done" || event.state === "completed";
  const time = timeRange(event);

  return (
    <li className="flex items-start gap-2.5 px-3.5 py-2 text-[13px]">
      {showKind ? (
        <span className={clsx("mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium", KIND_STYLE[event.kind])}>
          {t(`calendar.kind.${event.kind}` as const)}
        </span>
      ) : null}
      <div className="min-w-0 flex-1">
        <p className={clsx("leading-5", (done || cancelled) && "text-muted line-through")}>
          {event.kind === "event" ? (
            <button type="button" onClick={() => onEdit(event)} className="text-left hover:text-brand hover:underline">
              {label}
            </button>
          ) : href && !cancelled ? (
            <Link href={href} className="hover:text-brand hover:underline">
              {label}
            </Link>
          ) : (
            label
          )}
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted">
          {event.kind === "event" ? <span className="tabular">{time ?? t("calx.allDay")}</span> : null}
          {event.minutes && event.kind !== "event" ? <span className="tabular">{t("planner.minutes", { n: event.minutes })}</span> : null}
          {event.subject_name ? <span>{event.subject_name}</span> : null}
          {event.state === "overdue" ? <Badge tone="danger">{t("calx.overdue")}</Badge> : null}
          {cancelled ? <Badge>{t("pl.state.cancelled")}</Badge> : null}
          <SyncBadge state={event.sync} kind={event.kind} />
        </p>
        {event.kind === "event" && event.notes ? <p className="mt-1 line-clamp-2 text-xs text-muted">{event.notes}</p> : null}
      </div>
      {event.kind === "event" ? (
        <IconButton label={t("pl.edit")} onClick={() => onEdit(event)}>
          <Pencil className="h-3.5 w-3.5" aria-hidden />
        </IconButton>
      ) : null}
    </li>
  );
}
