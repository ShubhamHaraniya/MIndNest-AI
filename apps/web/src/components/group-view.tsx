"use client";

import clsx from "clsx";
import { ArrowLeft, Check, Copy, Download, FilePlus2, Flag, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Badge } from "@/components/kit/badge";
import { SearchField, Select } from "@/components/kit/controls";
import { EmptyState } from "@/components/kit/states";
import { Tabs } from "@/components/kit/tabs";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/kit/table";
import { DiscussionsTab } from "@/components/groups/discussions-tab";
import { MembersTab } from "@/components/groups/members-panel";
import { GROUP_TABS, isAdminRole, type GroupTab } from "@/components/groups/model";
import { NotesTab } from "@/components/groups/notes-tab";
import { SessionsTab } from "@/components/groups/sessions-tab";
import { Alert, Button, Field } from "@/components/ui";
import { useLocale, useT } from "@/i18n/client";
import type { MessageKey } from "@/i18n/translate";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { HIDE_AT_REPORTS, KIND_KEYS, MAX_NOTE_CHARS, REPORT_REASONS, RIGHTS, RIGHTS_KEYS, downloadUrl, formatSize } from "@/lib/groups";
import type { GroupDetail, ReportReason, ShareRights, Shareable, SharedItem, Subject, SubjectPage } from "@/lib/types";

const fieldClass = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm placeholder:text-muted";

type Pending =
  | { kind: "share" }
  | { kind: "edit" }
  | { kind: "add"; item: SharedItem }
  | { kind: "report"; item: SharedItem }
  | { kind: "remove_file"; item: SharedItem }
  | { kind: "leave" }
  | { kind: "delete_group" }
  | null;

export function GroupView({ groupId }: { groupId: string }) {
  const t = useT();
  const locale = useLocale();
  const router = useRouter();
  const [group, setGroup] = useState<GroupDetail | null>(null);
  const [items, setItems] = useState<SharedItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [copied, setCopied] = useState(false);
  const [tab, setTab] = useState<GroupTab>("files");

  const load = useCallback(async () => {
    try {
      const [detail, files] = await Promise.all([
        api<GroupDetail>(`/groups/${groupId}`),
        api<SharedItem[]>(`/groups/${groupId}/items`),
      ]);
      setGroup(detail);
      setItems(files);
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }, [groupId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const isOwner = group?.role === "owner";
  const isAdmin = group ? isAdminRole(group.role) : false;

  async function copyCode() {
    if (!group?.join_code) return;
    try {
      await navigator.clipboard.writeText(group.join_code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard can be blocked; the code is on screen to read out.
    }
  }

  async function newCode() {
    try {
      const updated = await api<GroupDetail>(`/groups/${groupId}/code`, { method: "POST" });
      setGroup((current) => (current ? { ...current, join_code: updated.join_code } : current));
      setNotice(t("lib.owner.code_changed"));
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }

  async function restore(item: SharedItem) {
    try {
      await api(`/groups/${groupId}/items/${item.id}/restore`, { method: "POST" });
      await load();
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }

  if (!group) {
    return error ? (
      <div className="space-y-4">
        <Alert>{error}</Alert>
        <Link href="/library" className="text-sm text-primary hover:underline">
          {t("lib.back")}
        </Link>
      </div>
    ) : (
      <p className="py-6 text-muted">{t("common.loading")}</p>
    );
  }

  return (
    <div className="space-y-6">
      <Link href="/library" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft className="h-4 w-4" aria-hidden />
        {t("lib.back")}
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-3 rounded-card border border-border bg-surface p-4 shadow-card sm:p-5">
        <div className="flex min-w-0 items-start gap-4">
          <span
            aria-hidden
            className="font-display flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-primary-soft text-2xl text-brand"
          >
            {group.name.trim().charAt(0).toUpperCase() || "?"}
          </span>
          <div className="min-w-0">
            <h1 className="font-display break-words text-xl leading-tight sm:text-2xl">{group.name}</h1>
            <p className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted">
              <Badge tone="brand">{t(`lib.role.${group.role}`)}</Badge>
              <span>{t("lib.card.members", { count: group.member_count })}</span>
            </p>
            {group.description ? <p className="mt-2 max-w-2xl text-sm text-muted">{group.description}</p> : null}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {isOwner ? (
            <>
              <Button variant="secondary" onClick={() => setPending({ kind: "edit" })}>
                {t("lib.owner.rename")}
              </Button>
              <Button variant="secondary" onClick={() => setPending({ kind: "delete_group" })}>
                {t("lib.owner.delete")}
              </Button>
            </>
          ) : (
            <Button variant="secondary" onClick={() => setPending({ kind: "leave" })}>
              {t("lib.members.leave")}
            </Button>
          )}
        </div>
      </header>

      {error ? <Alert>{error}</Alert> : null}
      {notice ? <Alert tone="success">{notice}</Alert> : null}

      {isOwner && group.join_code ? (
        <section className="rounded-card border border-border bg-surface p-4 shadow-card sm:p-5" aria-labelledby="group-code">
          <h2 id="group-code" className="font-semibold">
            {t("lib.owner.title")}
          </h2>
          <p className="mt-1 text-sm text-muted">{t("lib.owner.code_hint")}</p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <code className="rounded-xl bg-surface-3 px-4 py-2 text-lg font-semibold tracking-widest">{group.join_code}</code>
            <Button variant="secondary" onClick={() => void copyCode()}>
              {copied ? <Check className="h-4 w-4" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
              {copied ? t("lib.owner.copied") : t("lib.owner.copy")}
            </Button>
            <Button variant="ghost" onClick={() => void newCode()}>
              {t("lib.owner.new_code")}
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted">{t("lib.owner.new_code_hint")}</p>
        </section>
      ) : null}

      <Tabs
        label={group.name}
        value={tab}
        onChange={setTab}
        items={GROUP_TABS.map((id) => ({
          id,
          label: t(`gc.tab.${id}`),
          count: id === "files" ? items.length : id === "members" ? group.members.length : undefined,
        }))}
      />

      {tab === "files" ? (
        <section aria-labelledby="group-files" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="group-files" className="text-lg font-semibold">
              {t("lib.files.title")}
            </h2>
            <Button onClick={() => setPending({ kind: "share" })}>
              <FilePlus2 className="h-4 w-4" aria-hidden />
              {t("lib.files.share")}
            </Button>
          </div>
          <p className="text-xs text-muted">{t("lib.safety")}</p>

          <ItemsTable
            items={items}
            groupId={groupId}
            isAdmin={isAdmin}
            onAdd={(item) => setPending({ kind: "add", item })}
            onReport={(item) => setPending({ kind: "report", item })}
            onRemove={(item) => setPending({ kind: "remove_file", item })}
            onRestore={(item) => void restore(item)}
          />
        </section>
      ) : null}
      {tab === "notes" ? <NotesTab groupId={groupId} isAdmin={isAdmin} /> : null}
      {tab === "talk" ? <DiscussionsTab groupId={groupId} /> : null}
      {tab === "sessions" ? <SessionsTab groupId={groupId} /> : null}
      {tab === "members" ? <MembersTab group={group} onChanged={() => void load()} /> : null}

      <ShareDialog
        open={pending?.kind === "share"}
        groupId={groupId}
        onClose={() => setPending(null)}
        onDone={() => {
          setPending(null);
          setNotice(t("lib.share.done"));
          void load();
        }}
      />
      <EditDialog
        open={pending?.kind === "edit"}
        group={group}
        onClose={() => setPending(null)}
        onDone={() => {
          setPending(null);
          void load();
        }}
      />
      <AddDialog
        open={pending?.kind === "add"}
        groupId={groupId}
        item={pending?.kind === "add" ? pending.item : null}
        onClose={() => setPending(null)}
        onDone={() => {
          setPending(null);
          setNotice(t("lib.add.done"));
        }}
      />
      <ReportDialog
        open={pending?.kind === "report"}
        groupId={groupId}
        item={pending?.kind === "report" ? pending.item : null}
        onClose={() => setPending(null)}
        onDone={(hidden) => {
          setPending(null);
          setNotice(hidden ? t("lib.report.hidden_now") : t("lib.report.done"));
          void load();
        }}
      />
      <ConfirmDialog
        open={pending?.kind === "remove_file"}
        title={t("lib.confirm.remove_file")}
        text={t("lib.confirm.remove_file_text")}
        onClose={() => setPending(null)}
        run={async () => {
          if (pending?.kind !== "remove_file") return;
          await api(`/groups/${groupId}/items/${pending.item.id}`, { method: "DELETE" });
          setPending(null);
          await load();
        }}
      />
      <ConfirmDialog
        open={pending?.kind === "leave"}
        title={t("lib.confirm.leave")}
        text={t("lib.confirm.leave_text")}
        onClose={() => setPending(null)}
        run={async () => {
          await api(`/groups/${groupId}/leave`, { method: "POST" });
          router.push("/library");
        }}
      />
      <ConfirmDialog
        open={pending?.kind === "delete_group"}
        title={t("lib.confirm.delete_group")}
        text={t("lib.confirm.delete_group_text")}
        onClose={() => setPending(null)}
        run={async () => {
          await api(`/groups/${groupId}`, { method: "DELETE" });
          router.push("/library");
        }}
      />
    </div>
  );
}

function ConfirmDialog({
  open,
  title,
  text,
  onClose,
  run,
}: {
  open: boolean;
  title: string;
  text: string;
  onClose: () => void;
  run: () => Promise<void>;
}) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function go() {
    setBusy(true);
    setError(null);
    try {
      await run();
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={title}>
      <p className="text-sm text-muted">{text}</p>
      {error ? (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      ) : null}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          {t("common.cancel")}
        </Button>
        <Button variant="danger" loading={busy} onClick={() => void go()}>
          {t("lib.confirm.go")}
        </Button>
      </div>
    </Dialog>
  );
}

function EditDialog({
  open,
  group,
  onClose,
  onDone,
}: {
  open: boolean;
  group: GroupDetail;
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useT();
  const [name, setName] = useState(group.name);
  const [description, setDescription] = useState(group.description);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName(group.name);
      setDescription(group.description);
      setError(null);
    }
  }, [open, group]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/groups/${group.id}`, { method: "PATCH", body: { name, description } });
      onDone();
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("lib.edit.title")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {error ? <Alert>{error}</Alert> : null}
        <Field label={t("lib.create.name")} value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required />
        <div>
          <label htmlFor="edit-description" className="mb-1.5 block text-sm font-medium">
            {t("lib.create.description")}
          </label>
          <textarea
            id="edit-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={300}
            rows={3}
            className={fieldClass}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy} disabled={name.trim().length < 2}>
            {t("common.save")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function ShareDialog({
  open,
  groupId,
  onClose,
  onDone,
}: {
  open: boolean;
  groupId: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useT();
  const [options, setOptions] = useState<Shareable[] | null>(null);
  const [materialId, setMaterialId] = useState("");
  const [note, setNote] = useState("");
  const [rights, setRights] = useState(false);
  const [author, setAuthor] = useState("");
  const [institution, setInstitution] = useState("");
  const [basis, setBasis] = useState<ShareRights>("own_work");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setRights(false);
    setNote("");
    setAuthor("");
    setInstitution("");
    setBasis("own_work");
    api<Shareable[]>("/shareable-materials")
      .then((list) => {
        setOptions(list);
        setMaterialId(list[0]?.id ?? "");
      })
      .catch((caught: unknown) => setError(errorMessage(caught, t)));
  }, [open, t]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/groups/${groupId}/items`, {
        method: "POST",
        body: { material_id: materialId, note, author, institution, rights: basis, confirm_rights: rights },
      });
      onDone();
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("lib.share.title")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        <p className="text-sm text-muted">{t("lib.share.intro")}</p>
        {error ? <Alert>{error}</Alert> : null}
        {options !== null && options.length === 0 ? (
          <p className="text-sm text-muted">{t("lib.share.none")}</p>
        ) : (
          <>
            <div>
              <label htmlFor="share-file" className="mb-1.5 block text-sm font-medium">
                {t("lib.share.file")}
              </label>
              <select
                id="share-file"
                value={materialId}
                onChange={(e) => setMaterialId(e.target.value)}
                className={fieldClass}
                disabled={options === null}
              >
                {(options ?? []).map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.subject_name} · {option.filename}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="share-note" className="mb-1.5 block text-sm font-medium">
                {t("lib.share.note")}
              </label>
              <textarea
                id="share-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={MAX_NOTE_CHARS}
                rows={2}
                className={fieldClass}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("lg.share.author")} maxLength={120} value={author} onChange={(e) => setAuthor(e.target.value)} />
              <Field label={t("lg.share.institution")} maxLength={120} value={institution} onChange={(e) => setInstitution(e.target.value)} />
            </div>
            <p className="-mt-2 text-xs text-muted">{t("lg.share.credit")}</p>
            <div>
              <label htmlFor="share-basis" className="mb-1.5 block text-sm font-medium">
                {t("lg.rights.label")}
              </label>
              <select id="share-basis" value={basis} onChange={(e) => setBasis(e.target.value as ShareRights)} className={fieldClass}>
                {RIGHTS.map((value) => (
                  <option key={value} value={value}>
                    {t(RIGHTS_KEYS[value])}
                  </option>
                ))}
              </select>
            </div>
            <label className="flex items-start gap-3 text-sm">
              <input
                type="checkbox"
                checked={rights}
                onChange={(e) => setRights(e.target.checked)}
                className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
              />
              {t("lib.share.rights")}
            </label>
          </>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy} disabled={!rights || !materialId}>
            {t("lib.share.submit")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function AddDialog({
  open,
  groupId,
  item,
  onClose,
  onDone,
}: {
  open: boolean;
  groupId: string;
  item: SharedItem | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const t = useT();
  const [subjects, setSubjects] = useState<Subject[] | null>(null);
  const [subjectId, setSubjectId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    api<SubjectPage>("/subjects?limit=100")
      .then((page) => {
        setSubjects(page.items);
        setSubjectId(page.items[0]?.id ?? "");
      })
      .catch((caught: unknown) => setError(errorMessage(caught, t)));
  }, [open, t]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!item) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/groups/${groupId}/items/${item.id}/add`, { method: "POST", body: { subject_id: subjectId } });
      onDone();
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("lib.add.title")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        <p className="text-sm text-muted">{t("lib.add.intro")}</p>
        {error ? <Alert>{error}</Alert> : null}
        {subjects !== null && subjects.length === 0 ? (
          <p className="text-sm text-muted">{t("lib.add.nosubjects")}</p>
        ) : (
          <div>
            <label htmlFor="add-subject" className="mb-1.5 block text-sm font-medium">
              {t("lib.add.subject")}
            </label>
            <select
              id="add-subject"
              value={subjectId}
              onChange={(e) => setSubjectId(e.target.value)}
              className={fieldClass}
              disabled={subjects === null}
            >
              {(subjects ?? []).map((subject) => (
                <option key={subject.id} value={subject.id}>
                  {subject.name}
                </option>
              ))}
            </select>
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy} disabled={!subjectId}>
            {t("lib.add.submit")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function ReportDialog({
  open,
  groupId,
  item,
  onClose,
  onDone,
}: {
  open: boolean;
  groupId: string;
  item: SharedItem | null;
  onClose: () => void;
  onDone: (hidden: boolean) => void;
}) {
  const t = useT();
  const [reason, setReason] = useState<ReportReason>("copyright");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setError(null);
      setNote("");
      setReason("copyright");
    }
  }, [open]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!item) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ hidden: boolean }>(`/groups/${groupId}/items/${item.id}/report`, {
        method: "POST",
        body: { reason, note },
      });
      onDone(result.hidden);
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={t("lib.report.title")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        <p className="text-sm text-muted">{t("lib.report.intro", { count: HIDE_AT_REPORTS })}</p>
        {error ? <Alert>{error}</Alert> : null}
        <fieldset className="space-y-2">
          <legend className="mb-1.5 text-sm font-medium">{t("lib.report.reason")}</legend>
          {REPORT_REASONS.map((value) => (
            <label key={value} className="flex items-start gap-3 text-sm">
              <input
                type="radio"
                name="report-reason"
                checked={reason === value}
                onChange={() => setReason(value)}
                className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
              />
              {t(`lib.report.reason.${value}` as MessageKey)}
            </label>
          ))}
        </fieldset>
        <div>
          <label htmlFor="report-note" className="mb-1.5 block text-sm font-medium">
            {t("lib.report.note")}
          </label>
          <textarea
            id="report-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={MAX_NOTE_CHARS}
            rows={2}
            className={fieldClass}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy}>
            {t("lib.report.submit")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function ItemsTable({
  items,
  groupId,
  isAdmin,
  onAdd,
  onReport,
  onRemove,
  onRestore,
}: {
  items: SharedItem[];
  groupId: string;
  isAdmin: boolean;
  onAdd: (item: SharedItem) => void;
  onReport: (item: SharedItem) => void;
  onRemove: (item: SharedItem) => void;
  onRestore: (item: SharedItem) => void;
}) {
  const t = useT();
  const locale = useLocale();
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");

  if (items.length === 0) {
    return <EmptyState compact title={t("lib.files.empty")} />;
  }
  const needle = query.trim().toLowerCase();
  const shown = items.filter((item) => {
    if (kind && item.kind !== kind) return false;
    if (!needle) return true;
    return [item.filename, item.note, item.author, item.institution, item.course_name ?? "", item.shared_by_name].some((value) =>
      value.toLowerCase().includes(needle),
    );
  });

  return (
    <div className="rounded-card border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3.5 py-2">
        <SearchField value={query} onChange={setQuery} placeholder={t("lg.search")} className="w-full sm:w-60" />
        <Select aria-label={t("lg.filter.kind")} value={kind} onChange={(event) => setKind(event.target.value)}>
          <option value="">{t("lg.filter.all")}</option>
          {(Object.keys(KIND_KEYS) as (keyof typeof KIND_KEYS)[]).map((value) => (
            <option key={value} value={value}>
              {t(KIND_KEYS[value])}
            </option>
          ))}
        </Select>
        <p className="tabular ml-auto text-xs text-muted">{t("lg.count", { shown: shown.length, total: items.length })}</p>
      </div>
      {shown.length === 0 ? (
        <p className="px-3.5 py-4 text-[13px] text-muted">{t("lg.noMatch")}</p>
      ) : (
        <Table caption={t("lib.files.title")}>
          <THead>
            <tr>
              <Th>{t("lg.col.file")}</Th>
              <Th className="hidden md:table-cell">{t("lg.col.course")}</Th>
              <Th className="hidden lg:table-cell">{t("lg.col.source")}</Th>
              <Th className="hidden xl:table-cell">{t("lg.col.rights")}</Th>
              <Th className="hidden md:table-cell">{t("lg.col.sharedBy")}</Th>
              <Th>{t("lg.col.status")}</Th>
              <Th align="right">
                <span className="sr-only">{t("lg.col.actions")}</span>
              </Th>
            </tr>
          </THead>
          <TBody>
            {shown.map((item) => (
              <Tr key={item.id} className={item.status === "hidden" ? "bg-warning-soft/40" : undefined}>
                <Td className="max-w-[16rem]">
                  <p className="break-words font-medium">{item.filename}</p>
                  <p className="text-xs text-muted">{[t(KIND_KEYS[item.kind]), formatSize(item.size_bytes)].filter(Boolean).join(" · ")}</p>
                  {item.note ? <p className="mt-1 whitespace-pre-wrap break-words text-xs text-muted">{item.note}</p> : null}
                </Td>
                <Td className="hidden md:table-cell">{item.course_name ?? <span className="text-faint">{t("lg.unknown")}</span>}</Td>
                <Td className="hidden lg:table-cell">
                  {item.author || item.institution ? (
                    <>
                      <p>{item.author || <span className="text-faint">{t("lg.unknown")}</span>}</p>
                      {item.institution ? <p className="text-xs text-muted">{item.institution}</p> : null}
                    </>
                  ) : (
                    <span className="text-faint">{t("lg.unknown")}</span>
                  )}
                </Td>
                <Td className="hidden text-xs xl:table-cell">{t(RIGHTS_KEYS[item.rights])}</Td>
                <Td className="hidden md:table-cell">
                  <p>{item.mine ? t("lib.file.by_you") : item.shared_by_name}</p>
                  <p className="tabular text-xs text-muted">
                    {new Date(item.created_at).toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric" })}
                  </p>
                </Td>
                <Td>
                  {item.status === "hidden" ? (
                    <Badge tone="warning">
                      {t("lg.status.hidden")}
                      {item.reports !== null ? ` · ${t("lib.file.reports", { count: item.reports })}` : ""}
                    </Badge>
                  ) : (
                    <Badge tone="success">{t("lg.status.published")}</Badge>
                  )}
                </Td>
                <Td align="right">
                  <div className="flex flex-wrap items-center justify-end gap-1">
                    {item.status === "active" ? (
                      <>
                        <a
                          href={downloadUrl(groupId, item.id)}
                          aria-label={`${t("lib.file.download")}: ${item.filename}`}
                          className="inline-flex h-7 items-center gap-1 rounded-lg border border-border-strong px-2 text-xs font-medium hover:bg-surface-2"
                        >
                          <Download className="h-3.5 w-3.5" aria-hidden />
                          {t("lib.file.download")}
                        </a>
                        <Button variant="secondary" size="sm" onClick={() => onAdd(item)}>
                          {t("lib.file.add")}
                        </Button>
                      </>
                    ) : null}
                    {isAdmin && item.status === "hidden" ? (
                      <Button variant="secondary" size="sm" onClick={() => onRestore(item)}>
                        {t("lib.file.restore")}
                      </Button>
                    ) : null}
                    {item.can_report || item.reported_by_me ? (
                      <Button variant="ghost" size="sm" disabled={item.reported_by_me} onClick={() => onReport(item)}>
                        <Flag className="h-3.5 w-3.5" aria-hidden />
                        {item.reported_by_me ? t("lib.file.reported") : t("lib.file.report")}
                      </Button>
                    ) : null}
                    {item.can_remove ? (
                      <Button variant="ghost" size="icon" aria-label={`${t("lib.file.remove")}: ${item.filename}`} onClick={() => onRemove(item)}>
                        <Trash2 className="h-4 w-4" aria-hidden />
                      </Button>
                    ) : null}
                  </div>
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      )}
    </div>
  );
}
