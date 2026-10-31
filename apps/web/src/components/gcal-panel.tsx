"use client";

import clsx from "clsx";
import { CalendarCheck, CloudOff, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Dialog } from "@/components/dialog";
import { Badge } from "@/components/kit/badge";
import { Alert, Button } from "@/components/ui";
import { useLocale, useT } from "@/i18n/client";
import type { MessageKey } from "@/i18n/translate";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { parseDay } from "@/lib/planner";
import type { GcalChange, GcalState, GcalStatus, GcalSyncItem, GcalSyncResult } from "@/lib/types";

const START = "/api/v1/integrations/google-calendar/start";
const NOTICES = new Set(["connected", "cancelled", "error_failed", "error_signin", "error_no_refresh", "error_scope", "error_not_configured", "error_calendar_api"]);

const ACTION_STYLE = {
  create: "bg-success/10 text-success",
  update: "bg-primary-soft text-primary",
  delete: "bg-danger/10 text-danger",
} as const;

const changeKey = (c: GcalChange) => `${c.source_type}:${c.source_id}`;

/** Why a send failed, in words. The server keeps a short code; unknown ones get a general line. */
function failureText(code: string | null, t: ReturnType<typeof useT>): string {
  if (code === "rate_limited") return t("calx.err.busy");
  if (code === "google_unavailable" || code === "calendar_unavailable") return t("calx.err.unreachable");
  if (code === "google_401" || code === "google_403") return t("calx.err.refused");
  if (code?.startsWith("google_5")) return t("calx.err.server");
  return t("calx.err.other");
}

/** Connect Google Calendar, review what would be sent, and send only what the student ticks. */
export function GcalPanel({
  initialNotice,
  version = 0,
  onChanged,
}: {
  initialNotice?: string;
  /** Changes when something else on the page changed what is on Google. */
  version?: number;
  onChanged?: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const [status, setStatus] = useState<GcalStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "success" | "error" | "info"; text: string } | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [syncState, setSyncState] = useState<GcalState | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await api<GcalStatus>("/integrations/google-calendar"));
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load, version]);

  const live = Boolean(status?.connected && !status.needs_reconnect);
  useEffect(() => {
    if (!live) {
      setSyncState(null);
      return;
    }
    api<GcalState>("/integrations/google-calendar/state")
      .then(setSyncState)
      .catch(() => setSyncState(null));
  }, [live, version]);

  async function retry(items: GcalSyncItem[] | null) {
    setRetrying(items === null ? "all" : `${items[0].source_type}:${items[0].source_id}`);
    setError(null);
    try {
      const body = { items: (items ?? []).map((i) => ({ source_type: i.source_type, source_id: i.source_id })) };
      const result = await api<GcalSyncResult>("/integrations/google-calendar/retry", { method: "POST", body });
      const failed = result.failed.length;
      setNotice({
        tone: failed ? "error" : "success",
        text: failed
          ? t("calx.retry.some", { count: failed })
          : t("calx.retry.ok", { count: result.created + result.updated + result.deleted }),
      });
      onChanged?.();
      void load();
    } catch (caught) {
      setError(errorMessage(caught, t));
      if (caught instanceof ApiError && caught.code === "gcal_reconnect") void load();
    } finally {
      setRetrying(null);
    }
  }

  // Show what Google's redirect told us once, then tidy the address bar.
  useEffect(() => {
    if (!initialNotice || !NOTICES.has(initialNotice)) return;
    const tone = initialNotice === "connected" ? "success" : initialNotice === "cancelled" ? "info" : "error";
    setNotice({ tone, text: t(`gcal.notice.${initialNotice}` as MessageKey) });
    window.history.replaceState(null, "", window.location.pathname);
  }, [initialNotice, t]);

  if (status && !status.available && !status.connected) return null;

  const when = status?.last_synced_at
    ? new Date(status.last_synced_at).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" })
    : null;

  return (
    <section aria-labelledby="gcal-title" className="rounded-card border border-border bg-surface p-4 shadow-card sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 id="gcal-title" className="flex items-center gap-2 font-semibold">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary-soft text-brand"><CalendarCheck className="h-4 w-4" aria-hidden /></span>
            {t("gcal.title")}
          </h3>
          {status?.connected && !status.needs_reconnect ? (
            <p className="mt-1 text-sm text-muted">
              {t("gcal.connected")} {when ? t("gcal.last_synced", { when }) : t("gcal.never_synced")}
            </p>
          ) : (
            <p className="mt-1 text-sm text-muted">{status?.needs_reconnect ? t("gcal.reconnect_needed") : t("gcal.intro")}</p>
          )}
        </div>
        {status ? (
          <div className="flex flex-wrap items-center gap-2">
            {status.connected && !status.needs_reconnect ? (
              <>
                <Button onClick={() => setReviewing(true)}>{t("gcal.review")}</Button>
                <Button variant="secondary" onClick={() => setDisconnecting(true)}>
                  {t("gcal.disconnect")}
                </Button>
              </>
            ) : (
              <>
                {/* A plain link: the browser leaves the app for Google and comes back. */}
                <a
                  href={START}
                  className="inline-flex items-center justify-center rounded bg-primary px-4 py-2.5 text-sm font-medium text-on-primary transition-colors hover:bg-primary-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                >
                  {status.needs_reconnect ? t("gcal.reconnect") : t("gcal.connect")}
                </a>
                {status.connected ? (
                  <Button variant="secondary" onClick={() => setDisconnecting(true)}>
                    {t("gcal.disconnect")}
                  </Button>
                ) : null}
              </>
            )}
          </div>
        ) : null}
      </div>
      {syncState && live ? (
        <div className="mt-4 border-t border-border pt-3">
          <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]" aria-label={t("calx.sync.summary")}>
            <span className="text-success">{t("calx.count.synced", { count: syncState.synced })}</span>
            <span className="text-muted">{t("calx.count.pending", { count: syncState.pending })}</span>
            <span className={syncState.failed > 0 ? "font-medium text-danger" : "text-muted"}>
              {t("calx.count.failed", { count: syncState.failed })}
            </span>
          </p>
          {syncState.failed > 0 ? (
            <div className="mt-3 rounded border border-danger/40 bg-danger-soft">
              <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <p className="flex items-center gap-2 text-[13px] font-medium text-danger">
                  <CloudOff className="h-4 w-4" aria-hidden />
                  {t("calx.failed.title", { count: syncState.failed })}
                </p>
                <Button size="sm" onClick={() => void retry(null)} loading={retrying === "all"} disabled={retrying !== null}>
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                  {t("calx.retry.all")}
                </Button>
              </div>
              <ul className="divide-y divide-danger/20 border-t border-danger/20">
                {syncState.items
                  .filter((item) => item.state === "failed")
                  .map((item) => (
                    <li key={`${item.source_type}:${item.source_id}`} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-[13px]">
                      <div className="min-w-0 flex-1">
                        <p className="break-words">
                          {item.summary || `${t(`gcal.kind.${item.source_type}` as MessageKey)} · ${t("gcal.removed_item")}`}
                        </p>
                        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted">
                          <Badge tone="danger">{t(`gcal.action.${item.action}` as MessageKey)}</Badge>
                          <span>{failureText(item.error, t)}</span>
                          <span className="tabular">{t("calx.failed.attempts", { count: item.attempts })}</span>
                        </p>
                      </div>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => void retry([item])}
                        loading={retrying === `${item.source_type}:${item.source_id}`}
                        disabled={retrying !== null}
                      >
                        {t("calx.retry.one")}
                      </Button>
                    </li>
                  ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
      {error ? (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      ) : null}
      {notice ? (
        <div className="mt-3">
          <Alert tone={notice.tone}>{notice.text}</Alert>
        </div>
      ) : null}

      <ReviewDialog
        open={reviewing}
        onClose={() => setReviewing(false)}
        onSent={(result) => {
          setReviewing(false);
          const failed = result.failed.length;
          setNotice({
            tone: failed ? "error" : "success",
            text:
              t("gcal.done", { created: result.created, updated: result.updated, deleted: result.deleted }) +
              (failed ? ` ${t("gcal.some_failed", { count: failed })}` : ""),
          });
          void load();
          onChanged?.();
        }}
        onReconnect={() => {
          setReviewing(false);
          void load();
        }}
      />
      <DisconnectDialog
        open={disconnecting}
        onClose={() => setDisconnecting(false)}
        onDone={() => {
          setDisconnecting(false);
          setNotice(null);
          void load();
        }}
      />
    </section>
  );
}

function ReviewDialog({
  open,
  onClose,
  onSent,
  onReconnect,
}: {
  open: boolean;
  onClose: () => void;
  onSent: (result: GcalSyncResult) => void;
  onReconnect: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const [changes, setChanges] = useState<GcalChange[] | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setChanges(null);
    setError(null);
    api<{ changes: GcalChange[] }>("/integrations/google-calendar/preview")
      .then((response) => {
        if (cancelled) return;
        setChanges(response.changes);
        setTicked(new Set(response.changes.map(changeKey)));
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setError(errorMessage(caught, t));
        if (caught instanceof ApiError && caught.code === "gcal_reconnect") onReconnect();
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const all = useMemo(() => (changes ?? []).map(changeKey), [changes]);
  const everyTicked = all.length > 0 && all.every((key) => ticked.has(key));

  function toggle(key: string) {
    setTicked((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function send() {
    if (!changes) return;
    setSending(true);
    setError(null);
    try {
      const items = changes
        .filter((c) => ticked.has(changeKey(c)))
        .map((c) => ({ source_type: c.source_type, source_id: c.source_id }));
      onSent(await api<GcalSyncResult>("/integrations/google-calendar/sync", { method: "POST", body: { items } }));
    } catch (caught) {
      setError(errorMessage(caught, t));
      if (caught instanceof ApiError && caught.code === "gcal_reconnect") onReconnect();
    } finally {
      setSending(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("gcal.review_title")}>
      <p className="text-sm text-muted">{t("gcal.review_intro")}</p>
      <div className="mt-4 space-y-3">
        {error ? <Alert>{error}</Alert> : null}
        {changes === null && !error ? <p className="text-sm text-muted">{t("gcal.loading")}</p> : null}
        {changes?.length === 0 ? <Alert tone="info">{t("gcal.up_to_date")}</Alert> : null}
        {changes && changes.length > 0 ? (
          <>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={everyTicked}
                onChange={() => setTicked(everyTicked ? new Set() : new Set(all))}
                className="h-4 w-4 accent-primary"
              />
              {t("gcal.select_all")}
            </label>
            <ul className="max-h-72 space-y-1 overflow-y-auto rounded border border-border p-2">
              {changes.map((change) => {
                const key = changeKey(change);
                return (
                  <li key={key}>
                    <label className="flex cursor-pointer items-start gap-3 rounded-lg px-2 py-1.5 text-sm hover:bg-bg">
                      <input
                        type="checkbox"
                        checked={ticked.has(key)}
                        onChange={() => toggle(key)}
                        className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block break-words">
                          {change.summary || `${t(`gcal.kind.${change.source_type}` as MessageKey)} · ${t("gcal.removed_item")}`}
                        </span>
                        <span className="block text-xs text-muted">
                          {parseDay(change.day).toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" })}
                        </span>
                      </span>
                      <span className={clsx("shrink-0 rounded px-2 py-0.5 text-xs", ACTION_STYLE[change.action])}>
                        {t(`gcal.action.${change.action}` as MessageKey)}
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          </>
        ) : null}
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          {t("gcal.cancel")}
        </Button>
        {changes && changes.length > 0 ? (
          <Button onClick={() => void send()} loading={sending} disabled={ticked.size === 0}>
            {sending ? t("gcal.sending") : ticked.size === 1 ? t("gcal.send_one") : t("gcal.send", { count: ticked.size })}
          </Button>
        ) : null}
      </div>
    </Dialog>
  );
}

function DisconnectDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const t = useT();
  const [remove, setRemove] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await api(`/integrations/google-calendar?remove_events=${remove}`, { method: "DELETE" });
      setRemove(false);
      onDone();
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("gcal.disconnect_title")}>
      <p className="text-sm text-muted">{t("gcal.disconnect_text")}</p>
      <label className="mt-4 flex items-start gap-3 text-sm">
        <input
          type="checkbox"
          checked={remove}
          onChange={(event) => setRemove(event.target.checked)}
          className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
        />
        {t("gcal.disconnect_remove")}
      </label>
      {error ? (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      ) : null}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          {t("gcal.cancel")}
        </Button>
        <Button variant="danger" onClick={() => void confirm()} loading={busy}>
          {t("gcal.disconnect_confirm")}
        </Button>
      </div>
    </Dialog>
  );
}
