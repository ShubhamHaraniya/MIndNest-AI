"use client";

import { Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Button } from "@/components/kit/button";
import { ConfirmDialog } from "@/components/kit/confirm";
import { FormRow, Input, Select, Textarea } from "@/components/kit/controls";
import { useToast } from "@/components/kit/toast";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { CalendarEvent, GcalSyncResult, OwnEvent, Subject } from "@/lib/types";

import { newRequestKey } from "./model";

const MIN = 5;
const MAX = 1440;

/** Send one event to Google Calendar (or take it off) right after it was saved. What cannot be
 *  sent stays in the sync list with its reason, so it can be retried there. */
export async function pushEvent(id: string): Promise<GcalSyncResult> {
  return api<GcalSyncResult>("/integrations/google-calendar/sync", {
    method: "POST",
    body: { items: [{ source_type: "event", source_id: id }] },
  });
}

/** Add an event of your own, or change or delete one. */
export function EventDialog({
  open,
  event,
  defaultDay,
  subjects,
  googleConnected,
  onClose,
  onChanged,
}: {
  open: boolean;
  event: CalendarEvent | null;
  defaultDay: string;
  subjects: Subject[];
  googleConnected: boolean;
  onClose: () => void;
  /** Called after anything was saved, deleted or sent, so the page can reload. */
  onChanged: () => void;
}) {
  const t = useT();
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [day, setDay] = useState(defaultDay);
  const [allDay, setAllDay] = useState(false);
  const [time, setTime] = useState("09:00");
  const [minutes, setMinutes] = useState(60);
  const [subjectId, setSubjectId] = useState("");
  const [notes, setNotes] = useState("");
  const [send, setSend] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const key = useRef(newRequestKey());

  useEffect(() => {
    if (!open) return;
    key.current = newRequestKey();
    setTitle(event?.title ?? "");
    setDay(event?.day ?? defaultDay);
    setAllDay(event ? !event.start_time : false);
    setTime(event?.start_time || "09:00");
    setMinutes(event?.minutes ?? 60);
    setSubjectId(event?.subject_id ?? "");
    setNotes(event?.notes ?? "");
    setSend(event ? Boolean(event.sync_to_google) : googleConnected);
    setFailure(null);
    setBusy(false);
  }, [open, event, defaultDay, googleConnected]);

  const valid = title.trim() !== "" && day !== "" && minutes >= MIN && minutes <= MAX && (allDay || time !== "");

  async function push(id: string) {
    try {
      const result = await pushEvent(id);
      if (result.failed.length > 0) toast.error(t("calx.sync.failedToast"));
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  async function submit(submitted: FormEvent) {
    submitted.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setFailure(null);
    try {
      const body = {
        title: title.trim(),
        notes: notes.trim(),
        day,
        start_time: allDay ? "" : time,
        minutes,
        subject_id: subjectId || null,
        sync_to_google: googleConnected ? send : false,
      };
      const saved = event
        ? await api<OwnEvent>(`/calendar/events/${event.id}`, { method: "PATCH", body })
        : await api<OwnEvent>("/calendar/events", { method: "POST", body: { ...body, request_key: key.current } });
      toast.success(t(event ? "calx.saved" : "calx.added", { name: saved.title }));
      onClose();
      onChanged();
      // The student chose to send it (or it was already there): do it now, and again reload.
      if (googleConnected && (body.sync_to_google || event?.sync_to_google)) {
        await push(saved.id);
        onChanged();
      }
    } catch (caught) {
      setFailure(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!event?.id) return;
    const onGoogle = googleConnected && event.sync_to_google;
    try {
      await api(`/calendar/events/${event.id}`, { method: "DELETE" });
    } catch (caught) {
      toast.error(errorMessage(caught, t));
      return;
    }
    toast.success(t("calx.deleted"));
    onClose();
    onChanged();
    if (onGoogle) {
      await push(event.id);
      onChanged();
    }
  }

  return (
    <>
      <Dialog open={open} onClose={onClose} title={event ? t("calx.dialog.edit") : t("calx.dialog.add")}>
        <form onSubmit={(submitted) => void submit(submitted)} className="space-y-4">
          {failure ? (
            <p role="alert" className="text-sm text-danger">
              {failure}
            </p>
          ) : null}
          <FormRow label={t("calx.field.title")} htmlFor="event-title">
            <Input id="event-title" autoFocus value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
          </FormRow>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormRow label={t("planner.add.day")} htmlFor="event-day">
              <Input id="event-day" type="date" value={day} required onChange={(e) => setDay(e.target.value)} />
            </FormRow>
            <FormRow label={t("calx.field.time")} htmlFor="event-time">
              <Input id="event-time" type="time" value={time} disabled={allDay} onChange={(e) => setTime(e.target.value)} />
            </FormRow>
          </div>
          <label className="flex items-center gap-2 text-[13px]">
            <input type="checkbox" className="accent-primary" checked={allDay} onChange={(e) => setAllDay(e.target.checked)} />
            {t("calx.field.allDay")}
          </label>
          {!allDay ? (
            <FormRow label={t("planner.add.minutes")} htmlFor="event-minutes" hint={t("pl.dialog.minutesHint", { min: MIN, max: MAX })}>
              <Input
                id="event-minutes"
                type="number"
                min={MIN}
                max={MAX}
                step={5}
                value={minutes}
                onChange={(e) => setMinutes(Number(e.target.value) || 0)}
              />
            </FormRow>
          ) : null}
          <FormRow label={t("assign.create.subject")} htmlFor="event-subject">
            <Select id="event-subject" value={subjectId} onChange={(e) => setSubjectId(e.target.value)}>
              <option value="">{t("planner.exams.noSubject")}</option>
              {subjects.map((subject) => (
                <option key={subject.id} value={subject.id}>
                  {subject.name}
                </option>
              ))}
            </Select>
          </FormRow>
          <FormRow label={t("calx.field.notes")} htmlFor="event-notes">
            <Textarea id="event-notes" rows={3} value={notes} maxLength={1000} onChange={(e) => setNotes(e.target.value)} />
          </FormRow>
          {googleConnected ? (
            <label className="flex items-start gap-2 text-[13px]">
              <input type="checkbox" className="mt-0.5 accent-primary" checked={send} onChange={(e) => setSend(e.target.checked)} />
              <span>
                {t("calx.field.google")}
                <span className="block text-xs text-muted">{t("calx.field.googleHint")}</span>
              </span>
            </label>
          ) : null}
          <div className="flex items-center justify-between gap-2">
            {event ? (
              <Button type="button" variant="ghost" onClick={() => setRemoving(true)} disabled={busy}>
                <Trash2 className="h-4 w-4" aria-hidden />
                {t("common.delete")}
              </Button>
            ) : (
              <span />
            )}
            <div className="flex gap-2">
              <Button type="button" variant="secondary" onClick={onClose} disabled={busy}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" loading={busy} disabled={!valid}>
                {event ? t("common.save") : t("calx.add")}
              </Button>
            </div>
          </div>
        </form>
      </Dialog>

      <ConfirmDialog
        open={open && removing}
        title={t("calx.delete.title", { name: event?.title ?? "" })}
        description={event?.sync_to_google && googleConnected ? t("calx.delete.bodyGoogle") : t("calx.delete.body")}
        confirmLabel={t("common.delete")}
        onConfirm={remove}
        onClose={() => setRemoving(false)}
      />
    </>
  );
}
