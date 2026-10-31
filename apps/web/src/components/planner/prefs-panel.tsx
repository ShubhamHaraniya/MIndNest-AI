"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/kit/button";
import { Panel } from "@/components/kit/panel";
import { useLocale, useT } from "@/i18n/client";
import { WEEKDAYS, weekdayName } from "@/lib/planner";
import type { StudyPreferences } from "@/lib/types";

/** How many minutes a day the student can study and which weekdays are free. Overload is
 *  measured against this. */
export function PrefsPanel({
  prefs,
  onSave,
}: {
  prefs: StudyPreferences;
  onSave: (next: StudyPreferences) => Promise<boolean>;
}) {
  const t = useT();
  const locale = useLocale();
  const [minutes, setMinutes] = useState(prefs.daily_minutes);
  const [off, setOff] = useState<number[]>(prefs.days_off);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setMinutes(prefs.daily_minutes);
    setOff(prefs.days_off);
  }, [prefs.daily_minutes, prefs.days_off]);

  const changed = minutes !== prefs.daily_minutes || off.join(",") !== [...prefs.days_off].sort().join(",");

  function toggle(day: number) {
    setSaved(false);
    setOff((current) => (current.includes(day) ? current.filter((d) => d !== day) : [...current, day].sort()));
  }

  async function save() {
    setSaving(true);
    const ok = await onSave({ daily_minutes: minutes, days_off: off });
    setSaving(false);
    setSaved(ok);
  }

  return (
    <Panel id="prefs" title={t("planner.prefs.title")} description={t("pl.prefs.hint")}>
      <div className="space-y-4 px-3.5 py-3">
        <div>
          <label htmlFor="prefs-minutes" className="mb-1.5 block text-[13px]">
            {t("planner.prefs.daily")}: <span className="tabular font-medium">{minutes}</span> {t("planner.prefs.min")}
          </label>
          <input
            id="prefs-minutes"
            type="range"
            min={20}
            max={360}
            step={10}
            value={minutes}
            onChange={(event) => {
              setSaved(false);
              setMinutes(Number(event.target.value));
            }}
            className="w-full accent-primary"
          />
        </div>
        <fieldset>
          <legend className="mb-1.5 text-[13px]">{t("planner.prefs.off")}</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {WEEKDAYS.map((day) => (
              <label key={day} className="flex items-center gap-1.5 text-[13px]">
                <input
                  type="checkbox"
                  className="accent-primary"
                  checked={off.includes(day)}
                  onChange={() => toggle(day)}
                  disabled={!off.includes(day) && off.length >= 6}
                />
                {weekdayName(day, locale)}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex items-center gap-3">
          <Button size="sm" variant="secondary" loading={saving} disabled={!changed} onClick={() => void save()}>
            {t("planner.prefs.save")}
          </Button>
          {saved && !changed ? <span className="text-xs text-success">{t("assign.detail.saved")}</span> : null}
        </div>
      </div>
    </Panel>
  );
}
