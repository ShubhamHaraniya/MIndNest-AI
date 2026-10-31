"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { CalendarResponse, GcalStatus, StudyPreferences } from "@/lib/types";

/** The calendar for the days on screen. The previous days stay visible while the next ones load. */
export function useCalendarRange(first: string, last: string, version: number) {
  const t = useT();
  const [data, setData] = useState<CalendarResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const latest = useRef(0);

  const load = useCallback(async () => {
    const ticket = ++latest.current;
    setLoading(true);
    try {
      const response = await api<CalendarResponse>(`/calendar?from=${first}&to=${last}`);
      if (ticket !== latest.current) return;
      setData(response);
      setError(null);
    } catch (caught) {
      if (ticket === latest.current) setError(errorMessage(caught, t));
    } finally {
      if (ticket === latest.current) setLoading(false);
    }
  }, [first, last, t]);

  useEffect(() => {
    void load();
  }, [load, version]);

  return { data, error, loading, reload: load };
}

/** The daily study time and days off (to find overloaded days), and whether Google Calendar is
 *  connected (to offer sending an event there). Both are optional: the page works without them. */
export function useCalendarContext(version: number) {
  const [prefs, setPrefs] = useState<StudyPreferences | null>(null);
  const [google, setGoogle] = useState<GcalStatus | null>(null);

  useEffect(() => {
    api<StudyPreferences>("/planner/preferences").then(setPrefs).catch(() => setPrefs(null));
  }, []);
  useEffect(() => {
    api<GcalStatus>("/integrations/google-calendar").then(setGoogle).catch(() => setGoogle(null));
  }, [version]);

  return { prefs, googleConnected: Boolean(google?.connected && !google.needs_reconnect) };
}
