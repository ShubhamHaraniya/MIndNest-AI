"use client";

import { CheckCircle2 } from "lucide-react";
import { useMemo } from "react";

import { Panel } from "@/components/kit/panel";
import { useLocale, useT } from "@/i18n/client";
import { parseDay } from "@/lib/planner";
import type { CalendarEvent, StudyPreferences } from "@/lib/types";

type Conflict = { day: string; reason: string };

/** Days that ask too much of the student: more study planned than the daily time they chose,
 *  study planned on a day off, several deadlines at once, or heavy study on an exam day. */
export function Conflicts({
  days,
  byDay,
  prefs,
  onPick,
}: {
  days: string[];
  byDay: Map<string, CalendarEvent[]>;
  prefs: StudyPreferences;
  onPick: (day: string) => void;
}) {
  const t = useT();
  const locale = useLocale();

  const conflicts = useMemo(() => {
    const found: Conflict[] = [];
    const span = (minutes: number) =>
      minutes >= 60 ? t("cw.hours", { h: Math.floor(minutes / 60), m: minutes % 60 }) : t("cw.minutes", { n: minutes });
    for (const day of days) {
      const events = byDay.get(day) ?? [];
      const planned = events
        .filter((event) => event.kind === "task" && event.state !== "completed" && event.state !== "cancelled")
        .reduce((sum, event) => sum + (event.minutes ?? 0), 0);
      const deadlines = events.filter((event) => event.kind === "exam" || event.kind === "assignment").length;
      const weekday = (parseDay(day).getDay() + 6) % 7; // 0 = Monday, as in the preferences
      if (prefs.days_off.includes(weekday) && planned > 0) found.push({ day, reason: t("cw.dayOff") });
      else if (planned > prefs.daily_minutes) {
        found.push({ day, reason: t("cw.over", { planned: span(planned), capacity: span(prefs.daily_minutes) }) });
      }
      if (deadlines >= 2) found.push({ day, reason: t("cw.deadlines", { count: deadlines }) });
      if (events.some((event) => event.kind === "exam") && planned > 0 && planned >= prefs.daily_minutes * 0.75) {
        found.push({ day, reason: t("cw.examLoad", { planned: span(planned) }) });
      }
      // Two of the student's own timed events that overlap.
      const timed = events
        .filter((event) => event.kind === "event" && event.start_time)
        .map((event) => {
          const [h, m] = (event.start_time as string).split(":").map(Number);
          return { start: h * 60 + m, end: h * 60 + m + (event.minutes ?? 60) };
        })
        .sort((a, b) => a.start - b.start);
      if (timed.some((slot, index) => index > 0 && slot.start < timed[index - 1].end)) {
        found.push({ day, reason: t("calx.overlap") });
      }
    }
    return found;
  }, [days, byDay, prefs, t]);

  if (conflicts.length === 0) {
    return (
      <p className="flex items-center gap-2 rounded-card border border-success/30 bg-success-soft px-3.5 py-2 text-[13px] text-success">
        <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden />
        {t("calx.conflicts.ok")}
      </p>
    );
  }

  return (
    <Panel id="conflicts" title={t("cw.title")}>
      <ul className="divide-y divide-border">
          {conflicts.map((item, index) => (
            <li key={`${item.day}-${index}`}>
              <button
                type="button"
                onClick={() => onPick(item.day)}
                className="flex w-full items-baseline gap-3 px-3.5 py-2 text-left text-[13px] hover:bg-surface-2"
              >
                <span className="tabular w-28 shrink-0 font-medium">
                  {parseDay(item.day).toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" })}
                </span>
                <span className="text-muted">{item.reason}</span>
              </button>
            </li>
          ))}
      </ul>
    </Panel>
  );
}
