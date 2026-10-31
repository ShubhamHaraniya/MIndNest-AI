"use client";

import clsx from "clsx";
import { AlertTriangle, Bell, BellOff, CalendarClock, CalendarX2, CheckCheck, FileWarning, ListChecks, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Popover } from "@/components/kit/popover";
import { Skeleton } from "@/components/kit/skeleton";
import { useT } from "@/i18n/client";
import type { TFunction } from "@/i18n/translate";
import { api } from "@/lib/api";
import type { AppNotification } from "@/lib/types";

const REFRESH_MS = 60_000;

type Payload = { unread: number; items: AppNotification[] };

const ICONS: Record<AppNotification["kind"], typeof Bell> = {
  exam_soon: CalendarClock,
  assignment_due: CalendarClock,
  assignment_overdue: AlertTriangle,
  revision_due: RotateCcw,
  material_failed: FileWarning,
  calendar_reconnect: CalendarX2,
  tasks_today: ListChecks,
};

/** The sentence for one notification, in the student's language. */
export function notificationText(t: TFunction, n: AppNotification): string {
  const p = n.params;
  const title = String(p.title ?? "");
  const days = Number(p.days ?? 0);
  switch (n.kind) {
    case "exam_soon":
      return days === 0 ? t("notif.examToday", { title }) : days === 1 ? t("notif.examTomorrow", { title }) : t("notif.examDays", { title, days });
    case "assignment_due":
      return days === 0 ? t("notif.assignmentToday", { title }) : days === 1 ? t("notif.assignmentTomorrow", { title }) : t("notif.assignmentDays", { title, days });
    case "assignment_overdue":
      return t("notif.assignmentOverdue", { title, days });
    case "revision_due":
      return t("notif.revisionDue", { count: Number(p.count ?? 0) });
    case "material_failed":
      return t("notif.materialFailed", { filename: String(p.filename ?? "") });
    case "calendar_reconnect":
      return t("notif.calendarReconnect");
    case "tasks_today":
      return t("notif.tasksToday", { count: Number(p.count ?? 0), minutes: Number(p.minutes ?? 0) });
  }
}

const TONES = {
  info: "bg-info-soft text-info",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
};

export function NotificationsMenu() {
  const t = useT();
  const [data, setData] = useState<Payload | null>(null);
  const [failed, setFailed] = useState(false);
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const next = await api<Payload>("/notifications");
      if (alive.current) {
        setData(next);
        setFailed(false);
      }
    } catch {
      if (alive.current) setFailed(true);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    const onFocus = () => void load();
    window.addEventListener("focus", onFocus);
    return () => {
      alive.current = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [load]);

  async function markRead(keys: string[]) {
    setData((current) =>
      current ? { unread: Math.max(0, current.unread - keys.length), items: current.items.map((i) => (keys.includes(i.key) ? { ...i, read: true } : i)) } : current,
    );
    try {
      await api("/notifications/read", { method: "POST", body: { keys } });
    } catch {
      void load();
    }
  }

  async function markAll() {
    setData((current) => (current ? { unread: 0, items: current.items.map((i) => ({ ...i, read: true })) } : current));
    try {
      await api("/notifications/read-all", { method: "POST" });
    } catch {
      void load();
    }
  }

  const unread = data?.unread ?? 0;

  return (
    <Popover
      label={t("notif.title")}
      panelClassName="w-[min(24rem,calc(100vw-1.5rem))]"
      onOpenChange={(open) => open && void load()}
      trigger={({ open, toggle, id }) => (
        <button
          type="button"
          data-popover-trigger
          onClick={toggle}
          aria-expanded={open}
          aria-controls={open ? id : undefined}
          aria-label={unread > 0 ? t("notif.openUnread", { count: unread }) : t("notif.open")}
          className="relative flex h-8 w-8 items-center justify-center rounded text-muted transition-colors hover:bg-surface-3 hover:text-ink"
        >
          <Bell className="h-4 w-4" aria-hidden />
          {unread > 0 ? (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-sm bg-danger px-1 text-[10px] font-bold text-on-primary">
              {unread > 9 ? "9+" : unread}
            </span>
          ) : null}
        </button>
      )}
    >
      {(close) => (
        <div>
          <div className="flex items-center justify-between gap-2 border-b border-border px-3.5 py-2.5">
            <h2 className="font-display text-sm">{t("notif.title")}</h2>
            <button
              type="button"
              onClick={() => void markAll()}
              disabled={unread === 0}
              className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-brand transition-colors hover:bg-primary-soft disabled:pointer-events-none disabled:opacity-40"
            >
              <CheckCheck className="h-3.5 w-3.5" aria-hidden />
              {t("notif.markAll")}
            </button>
          </div>
          <div className="max-h-[26rem] overflow-y-auto">
            {data === null && !failed ? (
              <div className="space-y-3 p-4" role="status" aria-label={t("common.loading")}>
                {[0, 1, 2].map((i) => (
                  <div key={i} className="flex gap-3">
                    <Skeleton className="h-7 w-7 shrink-0" />
                    <div className="flex-1 space-y-2">
                      <Skeleton className="h-3.5 w-full" />
                      <Skeleton className="h-3 w-1/3" />
                    </div>
                  </div>
                ))}
              </div>
            ) : failed && data === null ? (
              <div className="p-6 text-center text-sm">
                <p className="text-muted">{t("notif.loadFailed")}</p>
                <button type="button" onClick={() => void load()} className="mt-3 font-medium text-brand hover:underline">
                  {t("common.retry")}
                </button>
              </div>
            ) : data && data.items.length === 0 ? (
              <div className="flex flex-col items-center px-6 py-10 text-center">
                <span className="flex h-9 w-9 items-center justify-center rounded bg-surface-3 text-muted">
                  <BellOff className="h-[18px] w-[18px]" aria-hidden />
                </span>
                <p className="mt-3 text-sm font-medium">{t("notif.emptyTitle")}</p>
                <p className="mt-1 text-xs text-muted">{t("notif.emptyBody")}</p>
              </div>
            ) : (
              <ul>
                {data?.items.map((n) => {
                  const Icon = ICONS[n.kind];
                  return (
                    <li key={n.key} className="border-b border-border last:border-0">
                      <Link
                        href={n.href}
                        onClick={() => {
                          if (!n.read) void markRead([n.key]);
                          close();
                        }}
                        className={clsx("flex gap-3 px-3.5 py-2.5 transition-colors hover:bg-surface-2", !n.read && "bg-primary-soft")}
                      >
                        <span className={clsx("flex h-7 w-7 shrink-0 items-center justify-center rounded", TONES[n.severity])}>
                          <Icon className="h-4 w-4" aria-hidden />
                        </span>
                        <span className="min-w-0 flex-1 text-sm leading-snug">{notificationText(t, n)}</span>
                        {!n.read ? <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" aria-label={t("notif.unread")} /> : null}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      )}
    </Popover>
  );
}
