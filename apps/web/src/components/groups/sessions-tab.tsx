"use client";

import { CalendarPlus, CalendarClock, MapPin, Plus } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Badge, type Tone } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { ConfirmDialog } from "@/components/kit/confirm";
import { FormRow, Input, Segmented, Select, Textarea } from "@/components/kit/controls";
import { EmptyState, ErrorState } from "@/components/kit/states";
import { useToast } from "@/components/kit/toast";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { formatDay } from "@/lib/format";
import type { CalendarAdded, GroupSession, Rsvp } from "@/lib/types";

import {
  MAX_SESSION_MINUTES,
  MIN_SESSION_MINUTES,
  SESSION_MINUTES,
  formatWhen,
  fromLocalInput,
  isOpen,
  nextHourInput,
  personName,
  toLocalInput,
} from "./model";

const STATE_TONE: Record<GroupSession["state"], Tone> = {
  upcoming: "info",
  ongoing: "success",
  past: "neutral",
  cancelled: "danger",
};
const RSVPS: Rsvp[] = ["going", "maybe", "declined"];

/** Study sessions the group plans together: when, how long, where, and who is coming. */
export function SessionsTab({ groupId }: { groupId: string }) {
  const t = useT();
  const [sessions, setSessions] = useState<GroupSession[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"coming" | "earlier">("coming");
  const [form, setForm] = useState<{ session: GroupSession | null } | null>(null);

  const load = useCallback(async () => {
    try {
      setSessions(await api<GroupSession[]>(`/groups/${groupId}/sessions`));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }, [groupId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function replace(updated: GroupSession) {
    setSessions((current) => (current ? current.map((s) => (s.id === updated.id ? updated : s)) : current));
  }

  if (error && !sessions) return <ErrorState compact description={error} onRetry={() => void load()} />;
  if (!sessions) return <p className="py-6 text-muted">{t("common.loading")}</p>;

  const coming = sessions.filter(isOpen);
  const earlier = sessions.filter((s) => !isOpen(s)).reverse();
  const shown = view === "coming" ? coming : earlier;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-[13px] text-muted">{t("gc.sessions.intro")}</p>
        <Button onClick={() => setForm({ session: null })}>
          <Plus className="h-4 w-4" aria-hidden />
          {t("gc.sessions.new")}
        </Button>
      </div>

      {sessions.length === 0 ? (
        <EmptyState icon={CalendarClock} title={t("gc.sessions.emptyTitle")} description={t("gc.sessions.emptyBody")}>
          <Button onClick={() => setForm({ session: null })}>{t("gc.sessions.new")}</Button>
        </EmptyState>
      ) : (
        <>
          <Segmented
            label={t("gc.sessions.view")}
            value={view}
            onChange={setView}
            options={[
              { value: "coming", label: t("gc.sessions.coming"), count: coming.length },
              { value: "earlier", label: t("gc.sessions.earlier"), count: earlier.length },
            ]}
          />
          {shown.length === 0 ? (
            <p className="rounded-card border border-dashed border-border p-5 text-sm text-muted">
              {view === "coming" ? t("gc.sessions.noneComing") : t("gc.sessions.noneEarlier")}
            </p>
          ) : (
            <ul className="space-y-3">
              {shown.map((session) => (
                <SessionCard
                  key={session.id}
                  groupId={groupId}
                  session={session}
                  onUpdated={replace}
                  onEdit={() => setForm({ session })}
                  onReload={() => void load()}
                />
              ))}
            </ul>
          )}
        </>
      )}

      <SessionForm
        open={form !== null}
        groupId={groupId}
        session={form?.session ?? null}
        onClose={() => setForm(null)}
        onSaved={() => {
          setForm(null);
          void load();
        }}
      />
    </div>
  );
}

function SessionCard({
  groupId,
  session,
  onUpdated,
  onEdit,
  onReload,
}: {
  groupId: string;
  session: GroupSession;
  onUpdated: (session: GroupSession) => void;
  onEdit: () => void;
  onReload: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const toast = useToast();
  const [working, setWorking] = useState<string | null>(null);
  const [asking, setAsking] = useState<"cancel" | "delete" | null>(null);
  const [showWho, setShowWho] = useState(false);

  const path = `/groups/${groupId}/sessions/${session.id}`;
  const open = isOpen(session);

  async function answer(response: Rsvp) {
    setWorking(response);
    try {
      if (session.my_response === response) {
        onUpdated(await api<GroupSession>(`${path}/rsvp`, { method: "DELETE" }));
      } else {
        onUpdated(await api<GroupSession>(`${path}/rsvp`, { method: "PUT", body: { response } }));
      }
    } catch (caught) {
      toast.error(errorMessage(caught, t));
      onReload();
    } finally {
      setWorking(null);
    }
  }

  async function addToCalendar() {
    setWorking("calendar");
    try {
      const added = await api<CalendarAdded>(`${path}/calendar`, { method: "POST" });
      const when = `${formatDay(added.day, locale, { day: "numeric", month: "short" })}, ${added.start_time}`;
      toast.success(t(added.already ? "gc.sessions.alreadyOnCalendar" : "gc.sessions.addedToCalendar", { when }));
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    } finally {
      setWorking(null);
    }
  }

  async function setStatus(status: "scheduled" | "cancelled") {
    try {
      onUpdated(await api<GroupSession>(path, { method: "PATCH", body: { status } }));
      toast.info(t(status === "cancelled" ? "gc.sessions.cancelled" : "gc.sessions.restored"));
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  async function remove() {
    try {
      await api(path, { method: "DELETE" });
      toast.success(t("gc.sessions.deleted"));
      onReload();
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  const going = session.attendees.filter((a) => a.response === "going");
  const maybe = session.attendees.filter((a) => a.response === "maybe");
  const declined = session.attendees.filter((a) => a.response === "declined");

  return (
    <li className="rounded-card border border-border bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="break-words font-semibold">{session.title}</h3>
            <Badge tone={STATE_TONE[session.state]}>{t(`gc.sessions.state.${session.state}`)}</Badge>
          </div>
          <p className="tabular mt-1 text-sm">
            {formatWhen(session.starts_at, locale)} · {t("gc.sessions.minutes", { count: session.minutes })}
          </p>
          {session.location ? (
            <p className="mt-0.5 flex items-center gap-1.5 break-words text-[13px] text-muted">
              <MapPin className="h-3.5 w-3.5 shrink-0" aria-hidden />
              {session.location}
            </p>
          ) : null}
          {session.description ? <p className="mt-1.5 whitespace-pre-wrap break-words text-[13px] text-muted">{session.description}</p> : null}
          <p className="mt-1.5 text-xs text-faint">
            {t("gc.sessions.setUpBy", { name: session.mine ? t("gc.byYou") : personName(session.created_by_name, t) })}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {open ? (
            <Button variant="secondary" size="sm" loading={working === "calendar"} onClick={() => void addToCalendar()}>
              <CalendarPlus className="h-3.5 w-3.5" aria-hidden />
              {t("gc.sessions.addToCalendar")}
            </Button>
          ) : null}
          {session.can_change && session.status === "scheduled" && open ? (
            <>
              <Button variant="ghost" size="sm" onClick={onEdit}>
                {t("common.edit")}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setAsking("cancel")}>
                {t("gc.sessions.cancel")}
              </Button>
            </>
          ) : null}
          {session.can_change && session.status === "cancelled" ? (
            <Button variant="ghost" size="sm" onClick={() => void setStatus("scheduled")}>
              {t("gc.sessions.restore")}
            </Button>
          ) : null}
          {session.can_change && !open ? (
            <Button variant="ghost" size="sm" onClick={() => setAsking("delete")}>
              {t("common.delete")}
            </Button>
          ) : null}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
        {open ? (
          <div role="group" aria-label={t("gc.sessions.yourAnswer")} className="flex flex-wrap gap-1.5">
            {RSVPS.map((response) => (
              <Button
                key={response}
                size="sm"
                variant={session.my_response === response ? "primary" : "secondary"}
                aria-pressed={session.my_response === response}
                loading={working === response}
                onClick={() => void answer(response)}
              >
                {t(`gc.sessions.rsvp.${response}`)}
              </Button>
            ))}
          </div>
        ) : (
          <span />
        )}
        <button type="button" className="text-xs text-brand underline-offset-2 hover:underline" aria-expanded={showWho} onClick={() => setShowWho((v) => !v)}>
          {t("gc.sessions.counts", { going: session.going, maybe: session.maybe, declined: session.declined })}
        </button>
      </div>

      {showWho ? (
        <div className="mt-2 grid gap-2 text-[13px] sm:grid-cols-3">
          {([
            ["going", going],
            ["maybe", maybe],
            ["declined", declined],
          ] as const).map(([key, people]) => (
            <div key={key}>
              <p className="text-xs font-medium text-muted">{t(`gc.sessions.rsvp.${key}`)}</p>
              {people.length === 0 ? (
                <p className="text-faint">—</p>
              ) : (
                <ul>
                  {people.map((a) => (
                    <li key={a.user_id} className="break-words">
                      {a.name}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      ) : null}

      <ConfirmDialog
        open={asking === "cancel"}
        title={t("gc.sessions.cancelTitle")}
        description={t("gc.sessions.cancelBody")}
        confirmLabel={t("gc.sessions.cancel")}
        onConfirm={() => setStatus("cancelled")}
        onClose={() => setAsking(null)}
      />
      <ConfirmDialog
        open={asking === "delete"}
        title={t("gc.sessions.deleteTitle")}
        description={t("gc.sessions.deleteBody")}
        confirmLabel={t("common.delete")}
        onConfirm={remove}
        onClose={() => setAsking(null)}
      />
    </li>
  );
}

function SessionForm({
  open,
  groupId,
  session,
  onClose,
  onSaved,
}: {
  open: boolean;
  groupId: string;
  /** null: plan a new session. */
  session: GroupSession | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT();
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [starts, setStarts] = useState("");
  const [minutes, setMinutes] = useState(60);
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setFailure(null);
    setBusy(false);
    setTitle(session?.title ?? "");
    setStarts(session ? toLocalInput(session.starts_at) : nextHourInput());
    setMinutes(session?.minutes ?? 60);
    setLocation(session?.location ?? "");
    setDescription(session?.description ?? "");
  }, [open, session]);

  const valid = title.trim().length > 0 && starts !== "" && minutes >= MIN_SESSION_MINUTES && minutes <= MAX_SESSION_MINUTES;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !valid) return;
    setBusy(true);
    setFailure(null);
    try {
      if (session === null) {
        await api(`/groups/${groupId}/sessions`, {
          method: "POST",
          body: { title: title.trim(), description, starts_at: fromLocalInput(starts), minutes, location },
        });
        toast.success(t("gc.sessions.planned"));
      } else {
        const changes: Record<string, string | number> = {};
        if (title.trim() !== session.title) changes.title = title.trim();
        if (description.trim() !== session.description) changes.description = description;
        if (location.trim() !== session.location) changes.location = location;
        if (minutes !== session.minutes) changes.minutes = minutes;
        // Only send the time when it was changed, so a session can be edited after it has begun.
        if (starts !== toLocalInput(session.starts_at)) changes.starts_at = fromLocalInput(starts);
        if (Object.keys(changes).length > 0) {
          await api(`/groups/${groupId}/sessions/${session.id}`, { method: "PATCH", body: changes });
        }
        toast.success(t("gc.sessions.updated"));
      }
      onSaved();
    } catch (caught) {
      setFailure(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  const options = SESSION_MINUTES.includes(minutes as (typeof SESSION_MINUTES)[number]) ? [...SESSION_MINUTES] : [...SESSION_MINUTES, minutes].sort((a, b) => a - b);

  return (
    <Dialog open={open} onClose={onClose} title={session ? t("gc.sessions.edit") : t("gc.sessions.new")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {failure ? (
          <p role="alert" className="text-sm text-danger">
            {failure}
          </p>
        ) : null}
        <FormRow label={t("gc.sessions.title")} htmlFor="session-title">
          <Input id="session-title" autoFocus value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} />
        </FormRow>
        <div className="grid gap-3 sm:grid-cols-2">
          <FormRow label={t("gc.sessions.starts")} htmlFor="session-starts" hint={t("gc.sessions.startsHint")}>
            <Input id="session-starts" type="datetime-local" value={starts} onChange={(event) => setStarts(event.target.value)} />
          </FormRow>
          <FormRow label={t("gc.sessions.length")} htmlFor="session-length">
            <Select id="session-length" value={minutes} onChange={(event) => setMinutes(Number(event.target.value))}>
              {options.map((value) => (
                <option key={value} value={value}>
                  {t("gc.sessions.minutes", { count: value })}
                </option>
              ))}
            </Select>
          </FormRow>
        </div>
        <FormRow label={t("gc.sessions.location")} htmlFor="session-location" hint={t("gc.sessions.locationHint")}>
          <Input id="session-location" value={location} maxLength={300} onChange={(event) => setLocation(event.target.value)} />
        </FormRow>
        <FormRow label={t("gc.sessions.description")} htmlFor="session-description">
          <Textarea id="session-description" rows={3} value={description} maxLength={1000} onChange={(event) => setDescription(event.target.value)} />
        </FormRow>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy} disabled={!valid}>
            {session ? t("common.save") : t("gc.sessions.plan")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
