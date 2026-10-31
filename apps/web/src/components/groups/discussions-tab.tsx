"use client";

import { ArrowLeft, Lock, LockOpen, MessageSquare, Pin, PinOff, Plus } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { Dialog } from "@/components/dialog";
import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { ConfirmDialog } from "@/components/kit/confirm";
import { FormRow, Input, SearchField, Textarea } from "@/components/kit/controls";
import { EmptyState, ErrorState, NoResults } from "@/components/kit/states";
import { useToast } from "@/components/kit/toast";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { relativeTime } from "@/lib/format";
import type { GroupPost, GroupThread, GroupThreadSummary } from "@/lib/types";

import { personName } from "./model";

const MAX_TITLE = 120;
const MAX_BODY = 5000;

/** Questions and answers inside the group. A thread has an opening post and replies; owners and
 *  admins can pin or lock a thread and remove replies. */
export function DiscussionsTab({ groupId }: { groupId: string }) {
  const t = useT();
  const locale = useLocale();
  const [threads, setThreads] = useState<GroupThreadSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setThreads(await api<GroupThreadSummary[]>(`/groups/${groupId}/threads`));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }, [groupId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  if (openId) {
    return (
      <ThreadView
        groupId={groupId}
        threadId={openId}
        onBack={() => {
          setOpenId(null);
          void load();
        }}
      />
    );
  }

  if (error && !threads) return <ErrorState compact description={error} onRetry={() => void load()} />;
  if (!threads) return <p className="py-6 text-muted">{t("common.loading")}</p>;

  const needle = query.trim().toLocaleLowerCase();
  const shown = needle ? threads.filter((th) => `${th.title} ${th.excerpt}`.toLocaleLowerCase().includes(needle)) : threads;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-[13px] text-muted">{t("gc.talk.intro")}</p>
        <Button onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" aria-hidden />
          {t("gc.talk.new")}
        </Button>
      </div>

      {threads.length === 0 ? (
        <EmptyState icon={MessageSquare} title={t("gc.talk.emptyTitle")} description={t("gc.talk.emptyBody")}>
          <Button onClick={() => setCreating(true)}>{t("gc.talk.new")}</Button>
        </EmptyState>
      ) : (
        <>
          <SearchField value={query} onChange={setQuery} placeholder={t("gc.talk.search")} className="w-full sm:w-72" />
          {shown.length === 0 ? (
            <NoResults title={t("gc.noMatch")} />
          ) : (
            <ul className="divide-y divide-border rounded-card border border-border bg-surface">
              {shown.map((thread) => (
                <li key={thread.id}>
                  <button
                    type="button"
                    onClick={() => setOpenId(thread.id)}
                    className="flex w-full items-start justify-between gap-3 px-3.5 py-3 text-left hover:bg-surface-2"
                  >
                    <span className="min-w-0">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="break-words font-medium">{thread.title}</span>
                        {thread.pinned ? (
                          <Badge tone="brand">
                            <Pin className="h-3 w-3" aria-hidden />
                            {t("gc.pinned")}
                          </Badge>
                        ) : null}
                        {thread.locked ? (
                          <Badge tone="warning">
                            <Lock className="h-3 w-3" aria-hidden />
                            {t("gc.talk.locked")}
                          </Badge>
                        ) : null}
                      </span>
                      {thread.excerpt ? <span className="mt-0.5 line-clamp-2 block break-words text-[13px] text-muted">{thread.excerpt}</span> : null}
                      <span className="mt-1 block text-xs text-faint">
                        {thread.mine ? t("gc.byYou") : personName(thread.author_name, t)} · {t("gc.talk.active", { when: relativeTime(thread.last_activity_at, locale) })}
                      </span>
                    </span>
                    <span className="tabular shrink-0 text-xs text-muted">{t("gc.talk.replies", { count: thread.reply_count })}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <ThreadForm
        open={creating}
        groupId={groupId}
        thread={null}
        onClose={() => setCreating(false)}
        onSaved={(saved) => {
          setCreating(false);
          void load();
          setOpenId(saved.id);
        }}
      />
    </div>
  );
}

function ThreadForm({
  open,
  groupId,
  thread,
  onClose,
  onSaved,
}: {
  open: boolean;
  groupId: string;
  /** null: a new discussion. */
  thread: GroupThread | null;
  onClose: () => void;
  onSaved: (thread: GroupThread) => void;
}) {
  const t = useT();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setTitle(thread?.title ?? "");
    setBody(thread?.body ?? "");
    setFailure(null);
  }, [open, thread]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !title.trim()) return;
    setBusy(true);
    setFailure(null);
    try {
      const saved = thread
        ? await api<GroupThread>(`/groups/${groupId}/threads/${thread.id}`, {
            method: "PATCH",
            body: { title: title.trim(), body },
          })
        : await api<GroupThread>(`/groups/${groupId}/threads`, { method: "POST", body: { title: title.trim(), body } });
      onSaved(saved);
    } catch (caught) {
      setFailure(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={thread ? t("gc.talk.edit") : t("gc.talk.new")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {failure ? (
          <p role="alert" className="text-sm text-danger">
            {failure}
          </p>
        ) : null}
        <FormRow label={t("gc.talk.title")} htmlFor="thread-title">
          <Input id="thread-title" autoFocus value={title} maxLength={MAX_TITLE} onChange={(event) => setTitle(event.target.value)} />
        </FormRow>
        <FormRow label={t("gc.talk.body")} htmlFor="thread-body" hint={t("gc.talk.bodyHint")}>
          <Textarea id="thread-body" rows={6} value={body} maxLength={MAX_BODY} onChange={(event) => setBody(event.target.value)} />
        </FormRow>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={busy} disabled={!title.trim()}>
            {thread ? t("common.save") : t("gc.talk.start")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

type Ask = { kind: "thread" } | { kind: "post"; post: GroupPost } | null;

function ThreadView({ groupId, threadId, onBack }: { groupId: string; threadId: string; onBack: () => void }) {
  const t = useT();
  const locale = useLocale();
  const toast = useToast();
  const [thread, setThread] = useState<GroupThread | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [editingPost, setEditingPost] = useState<{ id: string; body: string } | null>(null);
  const [savingPost, setSavingPost] = useState(false);
  const [editingThread, setEditingThread] = useState(false);
  const [ask, setAsk] = useState<Ask>(null);

  const path = `/groups/${groupId}/threads/${threadId}`;

  const load = useCallback(async () => {
    try {
      setThread(await api<GroupThread>(path));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }, [path, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function send(event: FormEvent) {
    event.preventDefault();
    if (sending || !reply.trim()) return;
    setSending(true);
    try {
      await api(`${path}/posts`, { method: "POST", body: { body: reply.trim() } });
      setReply("");
      await load();
    } catch (caught) {
      toast.error(errorMessage(caught, t));
      await load();
    } finally {
      setSending(false);
    }
  }

  async function savePost() {
    if (!editingPost || savingPost || !editingPost.body.trim()) return;
    setSavingPost(true);
    try {
      await api(`${path}/posts/${editingPost.id}`, { method: "PATCH", body: { body: editingPost.body.trim() } });
      setEditingPost(null);
      await load();
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    } finally {
      setSavingPost(false);
    }
  }

  async function flag(change: { pinned: boolean } | { locked: boolean }) {
    try {
      setThread(await api<GroupThread>(path, { method: "PATCH", body: change }));
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  async function confirmed() {
    if (!ask) return;
    try {
      if (ask.kind === "thread") {
        await api(path, { method: "DELETE" });
        toast.success(t("gc.talk.deleted"));
        onBack();
      } else {
        await api(`${path}/posts/${ask.post.id}`, { method: "DELETE" });
        await load();
      }
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  if (error && !thread) {
    return (
      <div className="space-y-3">
        <BackButton onBack={onBack} />
        <ErrorState compact description={error} onRetry={() => void load()} />
      </div>
    );
  }
  if (!thread) return <p className="py-6 text-muted">{t("common.loading")}</p>;

  const canReply = !thread.locked || thread.can_moderate;

  return (
    <div className="space-y-4">
      <BackButton onBack={onBack} />

      <article className="rounded-card border border-border bg-surface p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="break-words text-lg font-semibold">{thread.title}</h3>
            <p className="mt-0.5 text-xs text-muted">
              {thread.mine ? t("gc.byYou") : personName(thread.author_name, t)} · {relativeTime(thread.created_at, locale)}
              {thread.edited_at ? ` · ${t("gc.edited")}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {thread.pinned ? <Badge tone="brand">{t("gc.pinned")}</Badge> : null}
            {thread.locked ? <Badge tone="warning">{t("gc.talk.locked")}</Badge> : null}
            {thread.can_moderate ? (
              <>
                <Button variant="ghost" size="sm" onClick={() => void flag({ pinned: !thread.pinned })}>
                  {thread.pinned ? <PinOff className="h-3.5 w-3.5" aria-hidden /> : <Pin className="h-3.5 w-3.5" aria-hidden />}
                  {thread.pinned ? t("gc.unpin") : t("gc.pin")}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => void flag({ locked: !thread.locked })}>
                  {thread.locked ? <LockOpen className="h-3.5 w-3.5" aria-hidden /> : <Lock className="h-3.5 w-3.5" aria-hidden />}
                  {thread.locked ? t("gc.talk.unlock") : t("gc.talk.lock")}
                </Button>
              </>
            ) : null}
            {thread.can_edit ? (
              <Button variant="ghost" size="sm" onClick={() => setEditingThread(true)}>
                {t("common.edit")}
              </Button>
            ) : null}
            {thread.can_delete ? (
              <Button variant="ghost" size="sm" onClick={() => setAsk({ kind: "thread" })}>
                {t("common.delete")}
              </Button>
            ) : null}
          </div>
        </div>
        {thread.body ? <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-relaxed">{thread.body}</p> : null}
      </article>

      <section aria-label={t("gc.talk.repliesTitle", { count: thread.posts.length })} className="space-y-2">
        <h4 className="text-[13px] font-semibold">{t("gc.talk.repliesTitle", { count: thread.posts.length })}</h4>
        {thread.posts.length === 0 ? <p className="text-[13px] text-muted">{t("gc.talk.noReplies")}</p> : null}
        <ul className="space-y-2">
          {thread.posts.map((post) => (
            <li key={post.id} className="rounded-card border border-border bg-surface px-3.5 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-muted">
                  <span className="font-medium text-ink">{post.mine ? t("gc.byYou") : personName(post.author_name, t)}</span> ·{" "}
                  {relativeTime(post.created_at, locale)}
                  {post.edited_at ? ` · ${t("gc.edited")}` : ""}
                </p>
                <span className="flex gap-1">
                  {post.can_edit && editingPost?.id !== post.id ? (
                    <Button variant="ghost" size="sm" onClick={() => setEditingPost({ id: post.id, body: post.body })}>
                      {t("common.edit")}
                    </Button>
                  ) : null}
                  {post.can_delete ? (
                    <Button variant="ghost" size="sm" onClick={() => setAsk({ kind: "post", post })}>
                      {t("common.delete")}
                    </Button>
                  ) : null}
                </span>
              </div>
              {editingPost?.id === post.id ? (
                <div className="mt-2 space-y-2">
                  <label className="sr-only" htmlFor={`edit-${post.id}`}>
                    {t("gc.talk.reply")}
                  </label>
                  <Textarea
                    id={`edit-${post.id}`}
                    rows={3}
                    autoFocus
                    value={editingPost.body}
                    maxLength={MAX_BODY}
                    onChange={(event) => setEditingPost({ id: post.id, body: event.target.value })}
                  />
                  <div className="flex justify-end gap-2">
                    <Button variant="secondary" size="sm" disabled={savingPost} onClick={() => setEditingPost(null)}>
                      {t("common.cancel")}
                    </Button>
                    <Button size="sm" loading={savingPost} disabled={!editingPost.body.trim()} onClick={() => void savePost()}>
                      {t("common.save")}
                    </Button>
                  </div>
                </div>
              ) : (
                <p className="mt-1.5 whitespace-pre-wrap break-words text-sm leading-relaxed">{post.body}</p>
              )}
            </li>
          ))}
        </ul>
      </section>

      {canReply ? (
        <form onSubmit={(event) => void send(event)} className="space-y-2">
          <FormRow label={t("gc.talk.reply")} htmlFor="thread-reply" hint={thread.locked ? t("gc.talk.lockedAdmin") : undefined}>
            <Textarea id="thread-reply" rows={3} value={reply} maxLength={MAX_BODY} onChange={(event) => setReply(event.target.value)} />
          </FormRow>
          <div className="flex justify-end">
            <Button type="submit" loading={sending} disabled={!reply.trim()}>
              {t("gc.talk.send")}
            </Button>
          </div>
        </form>
      ) : (
        <p className="rounded-card border border-dashed border-border px-3.5 py-3 text-[13px] text-muted">{t("gc.talk.lockedNote")}</p>
      )}

      <ThreadForm
        open={editingThread}
        groupId={groupId}
        thread={thread}
        onClose={() => setEditingThread(false)}
        onSaved={(saved) => {
          setEditingThread(false);
          setThread(saved);
        }}
      />
      <ConfirmDialog
        open={ask !== null}
        title={ask?.kind === "thread" ? t("gc.talk.deleteTitle") : t("gc.talk.deletePostTitle")}
        description={ask?.kind === "thread" ? t("gc.talk.deleteBody") : t("gc.talk.deletePostBody")}
        confirmLabel={t("common.delete")}
        onConfirm={confirmed}
        onClose={() => setAsk(null)}
      />
    </div>
  );
}

function BackButton({ onBack }: { onBack: () => void }) {
  const t = useT();
  return (
    <button type="button" onClick={onBack} className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
      <ArrowLeft className="h-4 w-4" aria-hidden />
      {t("gc.talk.back")}
    </button>
  );
}
