"use client";

import clsx from "clsx";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Badge } from "@/components/kit/badge";
import { EmptyState } from "@/components/kit/states";
import { SkeletonText } from "@/components/kit/skeleton";
import { Table, TBody, THead, Td, Th, Tr } from "@/components/kit/table";
import { LibraryQueue } from "@/components/library/admin-queue";
import { Alert, Button } from "@/components/ui";
import { useLocale, useT } from "@/i18n/client";
import type { MessageKey } from "@/i18n/translate";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { formatSize } from "@/lib/groups";
import type {
  AdminAuditRow,
  AdminOverview,
  AdminReport,
  AdminSecurityRow,
  AdminUser,
  AdminUsers,
} from "@/lib/types";

const TABS = ["overview", "users", "reports", "library", "security"] as const;
type Tab = (typeof TABS)[number];
const PAGE = 25;
const fieldClass = "w-full rounded border border-border bg-surface px-3 py-2 text-sm placeholder:text-muted";

export function AdminView() {
  const t = useT();
  const [tab, setTab] = useState<Tab>("overview");
  return (
    <div className="space-y-6">
      <div role="tablist" aria-label={t("admin.tabs")} className="flex flex-wrap gap-1 border-b border-border">
        {TABS.map((name) => (
          <button
            key={name}
            role="tab"
            type="button"
            id={`admin-tab-${name}`}
            aria-selected={tab === name}
            aria-controls={`admin-panel-${name}`}
            onClick={() => setTab(name)}
            className={clsx(
              "-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors",
              tab === name ? "border-primary text-primary" : "border-transparent text-muted hover:text-ink",
            )}
          >
            {t(`admin.tab.${name}` as MessageKey)}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`admin-panel-${tab}`} aria-labelledby={`admin-tab-${tab}`}>
        {tab === "overview" ? <Overview /> : null}
        {tab === "users" ? <Users /> : null}
        {tab === "reports" ? <Reports /> : null}
        {tab === "library" ? <LibraryQueue /> : null}
        {tab === "security" ? <Security /> : null}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------ overview

const TILES: { key: string; label: MessageKey; format?: "bytes" }[] = [
  { key: "users_active", label: "admin.stat.users_active" },
  { key: "active_7d", label: "admin.stat.active_7d" },
  { key: "signups_7d", label: "admin.stat.signups_7d" },
  { key: "users_unverified", label: "admin.stat.users_unverified" },
  { key: "users_suspended", label: "admin.stat.users_suspended" },
  { key: "materials", label: "admin.stat.materials" },
  { key: "storage_bytes", label: "admin.stat.storage", format: "bytes" },
  { key: "materials_failed", label: "admin.stat.materials_failed" },
  { key: "chats_7d", label: "admin.stat.chats_7d" },
  { key: "ai_runs_7d", label: "admin.stat.ai_runs_7d" },
  { key: "ai_failed_7d", label: "admin.stat.ai_failed_7d" },
  { key: "tokens_7d", label: "admin.stat.tokens_7d" },
  { key: "quizzes_30d", label: "admin.stat.quizzes_30d" },
  { key: "assignment_runs_30d", label: "admin.stat.assignment_runs_30d" },
  { key: "groups", label: "admin.stat.groups" },
  { key: "shared_items", label: "admin.stat.shared_items" },
  { key: "reported_items", label: "admin.stat.reported_items" },
  { key: "security_events_7d", label: "admin.stat.security_events_7d" },
];

function Overview() {
  const t = useT();
  const locale = useLocale();
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<AdminOverview>("/admin/overview?days=30")
      .then(setData)
      .catch((caught: unknown) => setError(errorMessage(caught, t)));
  }, [t]);

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <p className="py-6 text-muted">{t("common.loading")}</p>;

  const peak = Math.max(1, ...data.series.map((p) => Math.max(p.signups, p.active_users)));
  const number = new Intl.NumberFormat(locale);
  return (
    <div className="space-y-6">
      <p className="text-sm text-muted">{t("admin.privacy")}</p>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
        {TILES.map((tile) => {
          const value = data.totals[tile.key] ?? 0;
          return (
            <div key={tile.key} className="rounded-card border border-border bg-surface p-4">
              <dt className="text-xs text-muted">{t(tile.label)}</dt>
              <dd className="mt-1 text-2xl font-semibold tabular-nums">
                {tile.format === "bytes" ? formatSize(value) : number.format(value)}
              </dd>
            </div>
          );
        })}
      </dl>
      <section className="rounded-card border border-border bg-surface p-5" aria-labelledby="admin-series">
        <h2 id="admin-series" className="font-semibold">
          {t("admin.series.title", { days: data.series.length })}
        </h2>
        <ul className="mt-2 flex gap-4 text-xs text-muted">
          <li className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-primary" aria-hidden />
            {t("admin.series.active")}
          </li>
          <li className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-success" aria-hidden />
            {t("admin.series.signups")}
          </li>
        </ul>
        <div className="mt-4 flex h-32 items-end gap-1" role="img" aria-label={t("admin.series.title", { days: data.series.length })}>
          {data.series.map((point) => (
            <div
              key={point.day}
              className="flex h-full flex-1 items-end gap-px"
              title={`${point.day}: ${t("admin.series.active")} ${point.active_users}, ${t("admin.series.signups")} ${point.signups}`}
            >
              <div className="w-1/2 rounded-t bg-primary" style={{ height: `${(point.active_users / peak) * 100}%` }} />
              <div className="w-1/2 rounded-t bg-success" style={{ height: `${(point.signups / peak) * 100}%` }} />
            </div>
          ))}
        </div>
        <table className="sr-only">
          <caption>{t("admin.series.title", { days: data.series.length })}</caption>
          <thead>
            <tr>
              <th>{t("admin.col.day")}</th>
              <th>{t("admin.series.active")}</th>
              <th>{t("admin.series.signups")}</th>
            </tr>
          </thead>
          <tbody>
            {data.series.map((point) => (
              <tr key={point.day}>
                <td>{point.day}</td>
                <td>{point.active_users}</td>
                <td>{point.signups}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

// ------------------------------------------------------------------------------ users

function Users() {
  const t = useT();
  const locale = useLocale();
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<AdminUsers | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<AdminUser | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api<AdminUsers>(`/admin/users?q=${encodeURIComponent(applied)}&limit=${PAGE}&offset=${offset}`));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }, [applied, offset, t]);

  useEffect(() => {
    void load();
  }, [load]);

  function search(event: FormEvent) {
    event.preventDefault();
    setOffset(0);
    setApplied(query.trim());
  }

  const date = (value: string | null) =>
    value ? new Date(value).toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric" }) : "–";

  return (
    <div className="space-y-4">
      <form onSubmit={search} className="flex flex-wrap gap-2" role="search">
        <label htmlFor="admin-search" className="sr-only">
          {t("admin.users.search")}
        </label>
        <input
          id="admin-search"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("admin.users.search")}
          maxLength={100}
          className={clsx(fieldClass, "max-w-sm")}
        />
        <Button type="submit" variant="secondary">
          {t("admin.users.find")}
        </Button>
      </form>
      {error ? <Alert>{error}</Alert> : null}
      {data === null ? (
        error ? null : <SkeletonText lines={4} className="py-4" />
      ) : data.items.length === 0 ? (
        <EmptyState compact title={t("admin.users.none")} />
      ) : (
        <>
          <div className="rounded-card border border-border bg-surface">
            <Table className="min-w-[56rem]" caption={t("admin.tab.users")}>
              <THead>
                <tr>
                  <Th>{t("admin.col.student")}</Th>
                  <Th>{t("admin.col.status")}</Th>
                  <Th>{t("admin.col.joined")}</Th>
                  <Th>{t("admin.col.last_seen")}</Th>
                  <Th align="right">{t("admin.col.subjects")}</Th>
                  <Th align="right">{t("admin.col.files")}</Th>
                  <Th align="right">{t("admin.col.storage")}</Th>
                  <Th align="right">{t("admin.col.chats")}</Th>
                  <Th>
                    <span className="sr-only">{t("admin.col.actions")}</span>
                  </Th>
                </tr>
              </THead>
              <TBody>
                {data.items.map((user) => (
                  <Tr key={user.id}>
                    <Td>
                      <div className="font-medium">{user.display_name}</div>
                      <div className="break-all text-xs text-muted">
                        {user.email}
                        {user.email_verified ? "" : ` · ${t("admin.unverified")}`}
                        {user.has_google ? " · Google" : ""}
                      </div>
                    </Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">
                        <Badge tone={user.status === "active" ? "success" : "danger"}>
                          {t(`admin.status.${user.status}` as MessageKey)}
                        </Badge>
                        {user.is_admin ? <Badge tone="brand">{t("admin.is_admin")}</Badge> : null}
                      </div>
                    </Td>
                    <Td className="text-muted">{date(user.created_at)}</Td>
                    <Td className="text-muted">{date(user.last_seen_at)}</Td>
                    <Td align="right" className="tabular-nums">{user.subjects}</Td>
                    <Td align="right" className="tabular-nums">{user.materials}</Td>
                    <Td align="right" className="tabular-nums">{formatSize(user.storage_bytes)}</Td>
                    <Td align="right" className="tabular-nums">{user.messages_30d}</Td>
                    <Td align="right">
                      {user.is_admin ? null : (
                        <Button variant="ghost" className="px-3 py-1.5" onClick={() => setTarget(user)}>
                          {user.status === "active" ? t("admin.users.suspend") : t("admin.users.activate")}
                        </Button>
                      )}
                    </Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          </div>
          <div className="flex items-center justify-between text-sm text-muted">
            <span>
              {t("admin.users.range", {
                from: offset + 1,
                to: offset + data.items.length,
                total: data.total,
              })}
            </span>
            <span className="flex gap-2">
              <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                {t("common.back")}
              </Button>
              <Button variant="secondary" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>
                {t("common.next")}
              </Button>
            </span>
          </div>
        </>
      )}
      <StatusDialog
        user={target}
        onClose={() => setTarget(null)}
        onDone={() => {
          setTarget(null);
          void load();
        }}
      />
    </div>
  );
}

function StatusDialog({ user, onClose, onDone }: { user: AdminUser | null; onClose: () => void; onDone: () => void }) {
  const t = useT();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const suspending = user?.status === "active";

  useEffect(() => {
    setReason("");
    setError(null);
  }, [user]);

  async function go() {
    if (!user) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/admin/users/${user.id}/status`, {
        method: "POST",
        body: { status: suspending ? "suspended" : "active", reason },
      });
      onDone();
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={user !== null}
      onClose={onClose}
      title={suspending ? t("admin.suspend.title", { name: user?.display_name ?? "" }) : t("admin.activate.title", { name: user?.display_name ?? "" })}
    >
      <p className="text-sm text-muted">{suspending ? t("admin.suspend.text") : t("admin.activate.text")}</p>
      <div className="mt-4">
        <label htmlFor="admin-reason" className="mb-1.5 block text-sm font-medium">
          {t("admin.reason")}
        </label>
        <input
          id="admin-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={300}
          className={fieldClass}
        />
      </div>
      {error ? (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      ) : null}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          {t("common.cancel")}
        </Button>
        <Button variant={suspending ? "danger" : "primary"} loading={busy} onClick={() => void go()}>
          {suspending ? t("admin.users.suspend") : t("admin.users.activate")}
        </Button>
      </div>
    </Dialog>
  );
}

// ------------------------------------------------------------------------------ reports

function Reports() {
  const t = useT();
  const [items, setItems] = useState<AdminReport[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<AdminReport | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setItems(await api<AdminReport[]>("/admin/reports"));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function dismiss(item: AdminReport) {
    try {
      await api(`/admin/reports/${item.item_id}/dismiss`, { method: "POST" });
      await load();
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }

  async function remove() {
    if (!removing) return;
    setBusy(true);
    try {
      await api(`/admin/reports/${removing.item_id}/remove`, { method: "POST", body: { reason } });
      setRemoving(null);
      setReason("");
      await load();
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">{t("admin.reports.intro")}</p>
      {error ? <Alert>{error}</Alert> : null}
      {items === null ? (
        error ? null : <SkeletonText lines={4} className="py-4" />
      ) : items.length === 0 ? (
        <p className="rounded-card border border-dashed border-border p-6 text-sm text-muted">{t("admin.reports.none")}</p>
      ) : (
        <ul className="space-y-3">
          {items.map((item) => (
            <li key={item.item_id} className="rounded-card border border-border bg-surface p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="break-words font-medium">{item.filename}</p>
                  <p className="mt-0.5 text-xs text-muted">
                    {t("admin.reports.in_group", { group: item.group_name })} ·{" "}
                    {t("admin.reports.by", { name: item.shared_by_name, email: item.shared_by_email })}
                  </p>
                  <p className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                    <span
                      className={clsx(
                        "rounded px-2 py-0.5 font-medium",
                        item.status === "hidden" ? "bg-warning/15 text-warning" : "bg-bg text-muted",
                      )}
                    >
                      {item.status === "hidden" ? t("lib.file.hidden") : t("admin.reports.visible")}
                    </span>
                    <span className="text-muted">{t("lib.file.reports", { count: item.reports })}</span>
                    {Object.entries(item.reasons).map(([reason, count]) => (
                      <span key={reason} className="rounded bg-bg px-2 py-0.5 text-muted">
                        {t(`lib.report.reason.${reason}` as MessageKey)} × {count}
                      </span>
                    ))}
                  </p>
                  {item.notes.length > 0 ? (
                    <ul className="mt-2 list-inside list-disc text-sm text-muted">
                      {item.notes.map((note, index) => (
                        <li key={index} className="break-words">
                          {note}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
                <div className="flex gap-2">
                  <Button variant="secondary" className="px-3 py-1.5" onClick={() => void dismiss(item)}>
                    {t("admin.reports.dismiss")}
                  </Button>
                  <Button variant="danger" className="px-3 py-1.5" onClick={() => setRemoving(item)}>
                    {t("admin.reports.remove")}
                  </Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      <Dialog open={removing !== null} onClose={() => setRemoving(null)} title={t("admin.reports.remove_title")}>
        <p className="text-sm text-muted">{t("admin.reports.remove_text")}</p>
        <div className="mt-4">
          <label htmlFor="admin-remove-reason" className="mb-1.5 block text-sm font-medium">
            {t("admin.reason")}
          </label>
          <input
            id="admin-remove-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            maxLength={300}
            className={fieldClass}
          />
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setRemoving(null)}>
            {t("common.cancel")}
          </Button>
          <Button variant="danger" loading={busy} onClick={() => void remove()}>
            {t("admin.reports.remove")}
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

// ------------------------------------------------------------------------------ security and audit

const KNOWN_KINDS = new Set(["pii_masked", "injection_in_source", "hidden_characters", "output_cleaned", "output_blocked"]);

function Security() {
  const t = useT();
  const locale = useLocale();
  const [days, setDays] = useState(7);
  const [rows, setRows] = useState<AdminSecurityRow[] | null>(null);
  const [audit, setAudit] = useState<AdminAuditRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRows(null);
    api<AdminSecurityRow[]>(`/admin/security?days=${days}`)
      .then(setRows)
      .catch((caught: unknown) => setError(errorMessage(caught, t)));
  }, [days, t]);

  useEffect(() => {
    api<AdminAuditRow[]>("/admin/audit?limit=50")
      .then(setAudit)
      .catch((caught: unknown) => setError(errorMessage(caught, t)));
  }, [t]);

  return (
    <div className="space-y-8">
      {error ? <Alert>{error}</Alert> : null}
      <section className="space-y-3" aria-labelledby="admin-security">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="admin-security" className="text-lg font-semibold">
            {t("admin.security.title")}
          </h2>
          <div className="flex gap-1" role="group" aria-label={t("admin.security.period")}>
            {[7, 30].map((value) => (
              <Button
                key={value}
                variant={days === value ? "primary" : "secondary"}
                className="px-3 py-1.5"
                aria-pressed={days === value}
                onClick={() => setDays(value)}
              >
                {t("admin.security.days", { days: value })}
              </Button>
            ))}
          </div>
        </div>
        <p className="text-sm text-muted">{t("admin.security.intro")}</p>
        {rows === null ? (
          <SkeletonText lines={3} className="py-2" />
        ) : rows.length === 0 ? (
          <EmptyState compact title={t("admin.security.none")} />
        ) : (
          <div className="rounded-card border border-border bg-surface">
            <Table caption={t("admin.security.title")}>
              <THead>
                <tr>
                  <Th>{t("admin.col.event")}</Th>
                  <Th align="right">{t("admin.col.events")}</Th>
                  <Th align="right">{t("admin.col.students")}</Th>
                </tr>
              </THead>
              <TBody>
                {rows.map((row) => (
                  <Tr key={row.kind}>
                    <Td>{KNOWN_KINDS.has(row.kind) ? t(`admin.kind.${row.kind}` as MessageKey) : row.kind}</Td>
                    <Td align="right" className="tabular-nums">{row.events}</Td>
                    <Td align="right" className="tabular-nums">{row.students}</Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          </div>
        )}
      </section>

      <section className="space-y-3" aria-labelledby="admin-audit">
        <h2 id="admin-audit" className="text-lg font-semibold">
          {t("admin.audit.title")}
        </h2>
        {audit === null ? (
          <SkeletonText lines={3} className="py-2" />
        ) : audit.length === 0 ? (
          <EmptyState compact title={t("admin.audit.none")} />
        ) : (
          <ul className="divide-y divide-border rounded-card border border-border bg-surface">
            {audit.map((entry) => {
              const reason = typeof entry.detail.reason === "string" ? entry.detail.reason : "";
              const filename = typeof entry.detail.filename === "string" ? entry.detail.filename : "";
              return (
                <li key={entry.id} className="px-4 py-2.5 text-sm">
                  <span className="font-medium">
                    {entry.action in AUDIT_KEYS ? t(AUDIT_KEYS[entry.action]) : entry.action}
                  </span>
                  {entry.target_email ? <span className="text-muted"> · {entry.target_email}</span> : null}
                  {filename ? <span className="text-muted"> · {filename}</span> : null}
                  {reason ? <span className="text-muted"> · “{reason}”</span> : null}
                  <div className="text-xs text-muted">
                    {entry.admin_name ?? t("admin.audit.system")} ·{" "}
                    {new Date(entry.created_at).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" })}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

const AUDIT_KEYS: Record<string, MessageKey> = {
  suspend_user: "admin.audit.suspend_user",
  activate_user: "admin.audit.activate_user",
  remove_shared_file: "admin.audit.remove_shared_file",
  dismiss_reports: "admin.audit.dismiss_reports",
  grant_admin: "admin.audit.grant_admin",
  revoke_admin: "admin.audit.revoke_admin",
};
