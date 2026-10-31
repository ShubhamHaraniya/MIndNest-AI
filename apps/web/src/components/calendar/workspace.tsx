"use client";

import { useState } from "react";

import { CalendarView } from "@/components/calendar-view";
import { GcalPanel } from "@/components/gcal-panel";
import type { Subject } from "@/lib/types";

/** The Google Calendar panel and the calendar side by side. When one changes what is on Google,
 *  the other reloads, so the "on Google" marks and the sync list always agree. */
export function CalendarWorkspace({ subjects, initialNotice }: { subjects: Subject[]; initialNotice?: string }) {
  const [version, setVersion] = useState(0);
  const bump = () => setVersion((n) => n + 1);
  return (
    <div className="space-y-6">
      <GcalPanel initialNotice={initialNotice} version={version} onChanged={bump} />
      <CalendarView subjects={subjects} version={version} onSyncChanged={bump} />
    </div>
  );
}
