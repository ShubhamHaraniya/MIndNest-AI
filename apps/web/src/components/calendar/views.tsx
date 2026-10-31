"use client";

import clsx from "clsx";
import { CalendarX, Plus } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { Button } from "@/components/kit/button";
import { Panel } from "@/components/kit/panel";
import { EmptyState } from "@/components/kit/states";
import { dayLabel, monthStart, weekDays } from "@/components/planner/model";
import { IconButton } from "@/components/subjects/bits";
import { useLocale, useT } from "@/i18n/client";
import { addDays, monthGrid, parseDay, weekdayName } from "@/lib/planner";
import type { CalendarEvent } from "@/lib/types";

import { EventLine, SyncBadge } from "./event-line";
import { KIND_DOT, KIND_EDGE, KIND_STYLE, eventHref, eventLabel, groupByDay, isCancelled, timeRange } from "./model";

type Shared = {
  events: CalendarEvent[];
  today: string;
  onEdit: (event: CalendarEvent) => void;
  onAdd: (day: string) => void;
};

function DayList({ day, events, onEdit, onAdd }: { day: string; events: CalendarEvent[]; onEdit: Shared["onEdit"]; onAdd: Shared["onAdd"] }) {
  const t = useT();
  const locale = useLocale();
  return (
    <Panel
      id={`day-${day}`}
      title={dayLabel(day, locale)}
      action={
        <Button size="sm" variant="secondary" onClick={() => onAdd(day)}>
          <Plus className="h-3.5 w-3.5" aria-hidden />
          {t("calx.add")}
        </Button>
      }
    >
      {events.length === 0 ? (
        <p className="px-3.5 py-6 text-center text-[13px] text-muted">{t("calendar.empty")}</p>
      ) : (
        <ul className="divide-y divide-border">
          {events.map((event, index) => (
            <EventLine key={`${event.kind}-${event.id ?? index}`} event={event} onEdit={onEdit} />
          ))}
        </ul>
      )}
    </Panel>
  );
}

/** A small coloured line for a grid cell: time (if any) and name, opens the event or its page. */
function Chip({ event, onEdit }: { event: CalendarEvent; onEdit: Shared["onEdit"] }) {
  const t = useT();
  const label = eventLabel(event, t);
  const href = eventHref(event);
  const time = event.kind === "event" ? event.start_time : "";
  const body = (
    <>
      {time ? <span className="tabular mr-1 opacity-80">{time}</span> : null}
      {label}
    </>
  );
  const classes = clsx(
    "block w-full truncate rounded-md border-l-2 px-1.5 py-0.5 text-left text-[11px] leading-4",
    KIND_STYLE[event.kind],
    KIND_EDGE[event.kind],
    isCancelled(event) && "line-through opacity-60",
  );
  if (event.kind === "event") {
    return (
      <button type="button" onClick={() => onEdit(event)} className={classes} title={label}>
        {body}
      </button>
    );
  }
  return href && !isCancelled(event) ? (
    <Link href={href} className={classes} title={label}>
      {body}
    </Link>
  ) : (
    <span className={classes} title={label}>
      {body}
    </span>
  );
}

// ------------------------------------------------------------------ month

export function MonthGrid({
  anchor,
  selected,
  onSelect,
  ...shared
}: Shared & { anchor: string; selected: string; onSelect: (day: string) => void }) {
  const t = useT();
  const locale = useLocale();
  const first = monthStart(anchor);
  const month = parseDay(first).getMonth();
  const grid = useMemo(() => monthGrid(parseDay(first).getFullYear(), month), [first, month]);
  const byDay = useMemo(() => groupByDay(shared.events), [shared.events]);

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto">
        <div className="grid min-w-[40rem] grid-cols-7 gap-px overflow-hidden rounded-card border border-border bg-border">
          {[0, 1, 2, 3, 4, 5, 6].map((index) => (
            <div key={index} className="bg-surface-2 px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted rtl:tracking-normal">
              {weekdayName(index, locale)}
            </div>
          ))}
          {grid.map((day) => {
            const events = byDay.get(day) ?? [];
            const inMonth = parseDay(day).getMonth() === month;
            return (
              <div
                key={day}
                className={clsx(
                  "flex min-h-24 flex-col gap-1 p-1.5",
                  selected === day ? "bg-primary-soft/40 outline outline-2 -outline-offset-2 outline-primary/70" : inMonth ? "bg-surface" : "bg-surface-2/60",
                )}
              >
                <button
                  type="button"
                  onClick={() => onSelect(day)}
                  aria-pressed={selected === day}
                  aria-label={`${dayLabel(day, locale)}${events.length ? ` · ${t("pl.month.tasks", { count: events.length })}` : ""}`}
                  className="flex"
                >
                  <span
                    className={clsx(
                      "tabular flex h-5 min-w-5 items-center justify-center rounded-full px-1 text-xs",
                      day === shared.today ? "bg-primary font-semibold text-on-primary" : inMonth ? "text-ink" : "text-faint",
                    )}
                  >
                    {parseDay(day).getDate()}
                  </span>
                </button>
                <div className="hidden min-w-0 flex-col gap-0.5 sm:flex">
                  {events.slice(0, 3).map((event, index) => (
                    <Chip key={`${event.kind}-${event.id ?? index}`} event={event} onEdit={shared.onEdit} />
                  ))}
                  {events.length > 3 ? (
                    <button type="button" onClick={() => onSelect(day)} className="px-1 text-left text-[11px] text-muted hover:text-ink">
                      {t("calendar.more", { count: events.length - 3 })}
                    </button>
                  ) : null}
                </div>
                {events.length > 0 ? (
                  <span className="flex gap-0.5 sm:hidden" aria-hidden>
                    {events.slice(0, 4).map((event, index) => (
                      <span key={index} className={clsx("h-1.5 w-1.5 rounded-full", KIND_DOT[event.kind])} />
                    ))}
                  </span>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
      <DayList day={selected} events={byDay.get(selected) ?? []} onEdit={shared.onEdit} onAdd={shared.onAdd} />
    </div>
  );
}

// ------------------------------------------------------------------ week

export function WeekGrid({ anchor, ...shared }: Shared & { anchor: string }) {
  const t = useT();
  const locale = useLocale();
  const days = weekDays(anchor);
  const byDay = useMemo(() => groupByDay(shared.events), [shared.events]);
  return (
    <div className="grid gap-2 md:grid-cols-4 xl:grid-cols-7">
      {days.map((day) => {
        const events = byDay.get(day) ?? [];
        return (
          <section
            key={day}
            aria-label={dayLabel(day, locale)}
            className={clsx(
              "flex min-h-32 flex-col gap-1.5 rounded-card border bg-surface p-2.5 shadow-card",
              day === shared.today ? "border-primary ring-2 ring-primary/15" : "border-border",
            )}
          >
            <header className="flex items-center justify-between gap-2">
              <p className={clsx("text-xs font-semibold", day === shared.today && "text-brand")}>
                {dayLabel(day, locale, "weekday")} <span className="tabular font-normal text-muted">{parseDay(day).getDate()}</span>
              </p>
              <IconButton label={t("pl.addOn", { day: dayLabel(day, locale, "short") })} onClick={() => shared.onAdd(day)} className="h-6 w-6">
                <Plus className="h-3.5 w-3.5" aria-hidden />
              </IconButton>
            </header>
            {events.length === 0 ? (
              <p className="text-xs text-faint">{t("pl.week.free")}</p>
            ) : (
              <ul className="space-y-1">
                {events.map((event, index) => (
                  <li key={`${event.kind}-${event.id ?? index}`} className="space-y-0.5">
                    <Chip event={event} onEdit={shared.onEdit} />
                    <SyncBadge state={event.sync} kind={event.kind} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ day

export function DayView({ day, ...shared }: Shared & { day: string }) {
  const t = useT();
  const byDay = useMemo(() => groupByDay(shared.events), [shared.events]);
  const events = byDay.get(day) ?? [];
  const allDay = events.filter((event) => !(event.kind === "event" && event.start_time));
  const timed = events.filter((event) => event.kind === "event" && event.start_time);
  return (
    <div className="space-y-4">
      {timed.length > 0 ? (
        <Panel id="day-timed" title={t("calx.day.schedule")}>
          <ul className="divide-y divide-border">
            {timed.map((event) => (
              <li key={event.id} className="grid grid-cols-[6.5rem_minmax(0,1fr)]">
                <p className="tabular border-r border-border px-3.5 py-2.5 text-xs font-medium text-muted">{timeRange(event)}</p>
                <ul>
                  <EventLine event={event} onEdit={shared.onEdit} showKind={false} />
                </ul>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
      <DayList day={day} events={allDay} onEdit={shared.onEdit} onAdd={shared.onAdd} />
    </div>
  );
}

// ------------------------------------------------------------------ agenda

export function Agenda({ anchor, days, ...shared }: Shared & { anchor: string; days: number }) {
  const t = useT();
  const locale = useLocale();
  const byDay = useMemo(() => groupByDay(shared.events), [shared.events]);
  const dated = useMemo(
    () => Array.from({ length: days }, (_, i) => addDays(anchor, i)).filter((day) => byDay.has(day)),
    [anchor, days, byDay],
  );
  if (dated.length === 0) {
    return (
      <EmptyState icon={CalendarX} title={t("calx.agenda.emptyTitle")} description={t("calx.agenda.emptyBody")}>
        <Button onClick={() => shared.onAdd(anchor)}>{t("calx.add")}</Button>
      </EmptyState>
    );
  }
  return (
    <div className="space-y-4">
      {dated.map((day) => (
        <section key={day} aria-label={dayLabel(day, locale)}>
          <h3 className="mb-1.5 flex items-baseline gap-2 text-[13px] font-semibold">
            {dayLabel(day, locale)}
            {day === shared.today ? <span className="text-xs font-normal text-brand">{t("planner.today")}</span> : null}
          </h3>
          <ul className="divide-y divide-border rounded-card border border-border bg-surface shadow-card">
            {(byDay.get(day) ?? []).map((event, index) => (
              <EventLine key={`${event.kind}-${event.id ?? index}`} event={event} onEdit={shared.onEdit} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
