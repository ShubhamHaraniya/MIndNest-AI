"use client";

import { NotebookPen, Pin, PinOff, Plus } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { ConfirmDialog } from "@/components/kit/confirm";
import { FormRow, Input, SearchField, Textarea } from "@/components/kit/controls";
import { EmptyState, ErrorState, NoResults } from "@/components/kit/states";
import { Skeleton } from "@/components/kit/skeleton";
import { useToast } from "@/components/kit/toast";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { relativeTime } from "@/lib/format";
import type { GroupNote, GroupNoteSummary } from "@/lib/types";

import { personName } from "./model";

const MAX_TITLE = 120;
const MAX_BODY = 20000;

type Open = { kind: "new" } | { kind: "open"; id: string } | null;

/** Notes the whole group can read: a place for summaries, formulas and answers worked out together.
 *  Anyone writes one; only its author changes the text; owners and admins can pin or remove any. */
export function NotesTab({ groupId, isAdmin }: { groupId: string; isAdmin: boolean }) {
  const t = useT();
  const locale = useLocale();
  const [notes, setNotes] = useState<GroupNoteSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Open>(null);

  const load = useCallback(async () => {
    try {
      setNotes(await api<GroupNoteSummary[]>(`/groups/${groupId}/notes`));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }, [groupId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !notes) return <ErrorState compact description={error} onRetry={() => void load()} />;
  if (!notes) return <Skeleton className="h-40 w-full" aria-hidden />;

  const needle = query.trim().toLocaleLowerCase();
  const shown = needle
    ? notes.filter((n) => `${n.title} ${n.excerpt}`.toLocaleLowerCase().includes(needle))
    : notes;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-[13px] text-muted">{t("gc.notes.intro")}</p>
        <Button onClick={() => setOpen({ kind: "new" })}>
          <Plus className="h-4 w-4" aria-hidden />
          {t("gc.notes.new")}
        </Button>
      </div>

      {notes.length === 0 ? (
        <EmptyState icon={NotebookPen} title={t("gc.notes.emptyTitle")} description={t("gc.notes.emptyBody")}>
          <Button onClick={() => setOpen({ kind: "new" })}>{t("gc.notes.new")}</Button>
        </EmptyState>
      ) : (
        <>
          <SearchField value={query} onChange={setQuery} placeholder={t("gc.notes.search")} className="w-full sm:w-72" />
          {shown.length === 0 ? (
            <NoResults title={t("gc.noMatch")} />
          ) : (
            <ul className="grid gap-3 sm:grid-cols-2">
              {shown.map((note) => (
                <li key={note.id}>
                  <button
                    type="button"
                    onClick={() => setOpen({ kind: "open", id: note.id })}
                    className="flex h-full w-full flex-col rounded-card border border-border bg-surface p-3.5 text-left hover:border-border-strong hover:bg-surface-2"
                  >
                    <span className="flex items-start justify-between gap-2">
                      <span className="min-w-0 break-words font-medium">{note.title}</span>
                      {note.pinned ? (
                        <Badge tone="brand">
                          <Pin className="h-3 w-3" aria-hidden />
                          {t("gc.pinned")}
                        </Badge>
                      ) : null}
                    </span>
                    {note.excerpt ? <span className="mt-1 line-clamp-3 whitespace-pre-line break-words text-[13px] text-muted">{note.excerpt}</span> : null}
                    <span className="mt-auto pt-2 text-xs text-faint">
                      {note.mine ? t("gc.byYou") : personName(note.author_name, t)} · {relativeTime(note.updated_at, locale)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <NoteDialog
        open={open !== null}
        groupId={groupId}
        noteId={open?.kind === "open" ? open.id : null}
        isAdmin={isAdmin}
        onClose={() => setOpen(null)}
        onChanged={() => void load()}
      />
    </div>
  );
}

function NoteDialog({
  open,
  groupId,
  noteId,
  isAdmin,
  onClose,
  onChanged,
}: {
  open: boolean;
  groupId: string;
  /** null: a new note. */
  noteId: string | null;
  isAdmin: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const toast = useToast();
  const [note, setNote] = useState<GroupNote | null>(null);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    if (!open) return;
    setFailure(null);
    setAsking(false);
    setBusy(false);
    if (noteId === null) {
      setNote(null);
      setEditing(true);
      setTitle("");
      setBody("");
      return;
    }
    setNote(null);
    setEditing(false);
    let current = true;
    api<GroupNote>(`/groups/${groupId}/notes/${noteId}`)
      .then((loaded) => {
        if (current) setNote(loaded);
      })
      .catch((caught: unknown) => {
        if (current) setFailure(errorMessage(caught, t));
      });
    return () => {
      current = false;
    };
  }, [open, noteId, groupId, t]);

  function startEdit() {
    if (!note) return;
    setTitle(note.title);
    setBody(note.body);
    setFailure(null);
    setEditing(true);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || !title.trim()) return;
    setBusy(true);
    setFailure(null);
    try {
      if (note === null) {
        await api<GroupNote>(`/groups/${groupId}/notes`, { method: "POST", body: { title: title.trim(), body } });
        toast.success(t("gc.notes.saved"));
        onChanged();
        onClose();
        return;
      }
      const changes: Record<string, string> = {};
      if (title.trim() !== note.title) changes.title = title.trim();
      if (body.trim() !== note.body) changes.body = body;
      if (Object.keys(changes).length > 0) {
        setNote(await api<GroupNote>(`/groups/${groupId}/notes/${note.id}`, { method: "PATCH", body: changes }));
        onChanged();
        toast.success(t("gc.notes.saved"));
      }
      setEditing(false);
    } catch (caught) {
      setFailure(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  async function togglePin() {
    if (!note) return;
    try {
      setNote(await api<GroupNote>(`/groups/${groupId}/notes/${note.id}`, { method: "PATCH", body: { pinned: !note.pinned } }));
      onChanged();
    } catch (caught) {
      setFailure(errorMessage(caught, t));
    }
  }

  async function remove() {
    if (!note) return;
    try {
      await api(`/groups/${groupId}/notes/${note.id}`, { method: "DELETE" });
      toast.success(t("gc.notes.deleted"));
      onChanged();
      onClose();
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  const heading = note === null && noteId === null ? t("gc.notes.new") : editing ? t("gc.notes.edit") : (note?.title ?? t("common.loading"));

  return (
    <>
      <Dialog open={open} onClose={onClose} title={heading} wide>
        {failure ? (
          <p role="alert" className="mb-3 text-sm text-danger">
            {failure}
          </p>
        ) : null}

        {editing ? (
          <form onSubmit={(event) => void save(event)} className="space-y-4">
            <FormRow label={t("gc.notes.title")} htmlFor="note-title">
              <Input id="note-title" autoFocus value={title} maxLength={MAX_TITLE} onChange={(event) => setTitle(event.target.value)} />
            </FormRow>
            <FormRow label={t("gc.notes.body")} htmlFor="note-body" hint={t("gc.notes.bodyHint", { count: body.length, max: MAX_BODY })}>
              <Textarea id="note-body" rows={12} value={body} maxLength={MAX_BODY} onChange={(event) => setBody(event.target.value)} />
            </FormRow>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" disabled={busy} onClick={() => (note ? setEditing(false) : onClose())}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" loading={busy} disabled={!title.trim()}>
                {t("common.save")}
              </Button>
            </div>
          </form>
        ) : note ? (
          <div className="space-y-4">
            <p className="text-xs text-muted">
              {note.mine ? t("gc.byYou") : personName(note.author_name, t)} · {t("gc.updated", { when: relativeTime(note.updated_at, locale) })}
              {note.pinned ? ` · ${t("gc.pinned")}` : ""}
            </p>
            {note.body ? (
              <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">{note.body}</p>
            ) : (
              <p className="text-sm text-muted">{t("gc.notes.noBody")}</p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              {isAdmin ? (
                <Button variant="ghost" onClick={() => void togglePin()}>
                  {note.pinned ? <PinOff className="h-4 w-4" aria-hidden /> : <Pin className="h-4 w-4" aria-hidden />}
                  {note.pinned ? t("gc.unpin") : t("gc.pin")}
                </Button>
              ) : null}
              {note.can_change ? (
                <Button variant="ghost" onClick={() => setAsking(true)}>
                  {t("common.delete")}
                </Button>
              ) : null}
              {note.mine ? <Button onClick={startEdit}>{t("common.edit")}</Button> : null}
            </div>
          </div>
        ) : failure ? null : (
          <Skeleton className="h-32 w-full" aria-hidden />
        )}
      </Dialog>

      <ConfirmDialog
        open={asking}
        title={t("gc.notes.deleteTitle")}
        description={t("gc.notes.deleteBody")}
        confirmLabel={t("gc.notes.deleteConfirm")}
        onConfirm={remove}
        onClose={() => setAsking(false)}
      />
    </>
  );
}
