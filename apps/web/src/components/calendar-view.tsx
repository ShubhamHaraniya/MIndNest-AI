"use client";

import { CalendarPlus, ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/kit/button";
import { Segmented } from "@/components/kit/controls";
import { ErrorState } from "@/components/kit/states";
import { Skeleton } from "@/components/kit/skeleton";
import { IconButton } from "@/components/subjects/bits";
import { useLocale, useT } from "@/i18n/client";
import { addDays, formatDay, monthGrid, parseDay } from "@/lib/planner";
import type { CalendarEvent, Subject } from "@/lib/types";

import { dayLabel, monthStart, shiftMonth, weekDays } from "./planner/model";
import { Conflicts } from "./calendar/conflicts";
import { EventDialog } from "./calendar/event-dialog";
import { AGENDA_DAYS, KINDS, KIND_DOT, MODES, groupByDay, type CalendarMode } from "./calendar/model";
import { useCalendarContext, useCalendarRange } from "./calendar/use-calendar";
import { Agenda, DayView, MonthGrid, WeekGrid } from "./calendar/views";

/** The calendar: Month, Week, Day and Agenda over the same events (exams, deadlines, study tasks,
 *  revision, and the events the student adds), with a way to add one. `version` changes when the
 *  Google panel sent something, so the sync marks here stay current. */
export function CalendarView({
  subjects,
  version,
  onSyncChanged,
}: {
  subjects: Subject[];
  version: number;
  onSyncChanged: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const [mode, setMode] = useState<CalendarMode>("month");
  const [anchor, setAnchor] = useState(() => formatDay(new Date()));
  const [selected, setSelected] = useState(() => formatDay(new Date()));
  const [dialog, setDialog] = useState<{ event: CalendarEvent | null; day: string } | null>(null);
  const [localVersion, setLocalVersion] = useState(0);

  const range = useMemo(() => {
    switch (mode) {
      case "month": {
        const grid = monthGrid(parseDay(monthStart(anchor)).getFullYear(), parseDay(monthStart(anchor)).getMonth());
        return { first: grid[0], last: grid[grid.length - 1] };
      }
      case "week": {
        const days = weekDays(anchor);
        return { first: days[0], last: days[6] };
      }
      case "day":
        return { first: anchor, last: anchor };
      default:
        return { first: anchor, last: addDays(anchor, AGENDA_DAYS - 1) };
    }
  }, [mode, anchor]);

  const { data, error, loading, reload } = useCalendarRange(range.first, range.last, version + localVersion);
  const { prefs, googleConnected } = useCalendarContext(version + localVersion);
  const today = data?.today ?? formatDay(new Date());
  const events = data?.events ?? [];
  const byDay = useMemo(() => groupByDay(events), [events]);

  function step(direction: -1 | 1) {
    if (mode === "month") setAnchor(shiftMonth(anchor, direction));
    else if (mode === "week") setAnchor(addDays(anchor, 7 * direction));
    else if (mode === "day") setAnchor(addDays(anchor, direction));
    else setAnchor(addDays(anchor, AGENDA_DAYS * direction));
  }

  function goToday() {
    setAnchor(today);
    setSelected(today);
  }

  function changed() {
    setLocalVersion((n) => n + 1);
    onSyncChanged();
  }

  const title =
    mode === "month"
      ? parseDay(monthStart(anchor)).toLocaleDateString(locale, { month: "long", year: "numeric" })
      : mode === "day"
        ? dayLabel(anchor, locale)
        : `${dayLabel(range.first, locale, "short")} – ${dayLabel(range.last, locale, "short")}`;

  const visibleDays = useMemo(() => {
    const days: string[] = [];
    for (let day = range.first; day <= range.last; day = addDays(day, 1)) {
      if (mode !== "month" || parseDay(day).getMonth() === parseDay(monthStart(anchor)).getMonth()) days.push(day);
    }
    return days;
  }, [range, mode, anchor]);

  const prevLabel = t(mode === "month" ? "pl.nav.prevMonth" : mode === "week" ? "pl.nav.prevWeek" : mode === "day" ? "calx.nav.prevDay" : "calx.nav.prevPage");
  const nextLabel = t(mode === "month" ? "pl.nav.nextMonth" : mode === "week" ? "pl.nav.nextWeek" : mode === "day" ? "calx.nav.nextDay" : "calx.nav.nextPage");

  const shared = {
    events,
    today,
    onEdit: (event: CalendarEvent) => setDialog({ event, day: event.day }),
    onAdd: (day: string) => setDialog({ event: null, day }),
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-surface px-4 py-3 shadow-card">
        <div className="flex flex-wrap items-center gap-2">
          <IconButton label={prevLabel} onClick={() => step(-1)}>
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </IconButton>
          <IconButton label={nextLabel} onClick={() => step(1)}>
            <ChevronRight className="h-4 w-4" aria-hidden />
          </IconButton>
          <h2 className="font-display min-w-40 text-lg capitalize" aria-live="polite">
            {title}
          </h2>
          <Button size="sm" variant="secondary" onClick={goToday}>
            {t("calendar.today")}
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            value={mode}
            onChange={setMode}
            label={t("calx.mode.label")}
            options={MODES.map((value) => ({ value, label: t(`calx.mode.${value}` as const) }))}
          />
          <Button size="sm" onClick={() => setDialog({ event: null, day: mode === "month" ? selected : anchor })}>
            <CalendarPlus className="h-3.5 w-3.5" aria-hidden />
            {t("calx.add")}
          </Button>
        </div>
      </div>

      <ul className="flex flex-wrap gap-x-4 gap-y-1.5 px-1 text-xs text-muted" aria-label={t("calendar.legend")}>
        {KINDS.map((kind) => (
          <li key={kind} className="inline-flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${KIND_DOT[kind]}`} aria-hidden />
            {t(`calendar.kind.${kind}` as const)}
          </li>
        ))}
      </ul>

      {error && !data ? (
        <ErrorState compact description={error} onRetry={() => void reload()} />
      ) : !data ? (
        <div className="space-y-3" aria-hidden>
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-72 w-full" />
        </div>
      ) : (
        <div className={loading ? "opacity-70 transition-opacity" : "transition-opacity"} aria-busy={loading}>
          {error ? (
            <p role="alert" className="mb-3 text-sm text-danger">
              {error}
            </p>
          ) : null}
          {prefs && mode !== "agenda" ? (
            <div className="mb-4">
              <Conflicts
                days={visibleDays}
                byDay={byDay}
                prefs={prefs}
                onPick={(day) => {
                  setSelected(day);
                  if (mode === "week") setAnchor(day);
                  else if (mode === "day") setAnchor(day);
                }}
              />
            </div>
          ) : null}
          {mode === "month" ? <MonthGrid {...shared} anchor={anchor} selected={selected} onSelect={setSelected} /> : null}
          {mode === "week" ? <WeekGrid {...shared} anchor={anchor} /> : null}
          {mode === "day" ? <DayView {...shared} day={anchor} /> : null}
          {mode === "agenda" ? <Agenda {...shared} anchor={anchor} days={AGENDA_DAYS} /> : null}
        </div>
      )}

      <EventDialog
        open={dialog !== null}
        event={dialog?.event ?? null}
        defaultDay={dialog?.day ?? today}
        subjects={subjects}
        googleConnected={googleConnected}
        onClose={() => setDialog(null)}
        onChanged={changed}
      />
    </div>
  );
}
