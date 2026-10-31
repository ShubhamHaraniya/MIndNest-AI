"use client";

import clsx from "clsx";
import { Check, MessageSquarePlus, Pencil, Search, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/kit/button";
import { useT } from "@/i18n/client";
import type { TFunction } from "@/i18n/translate";
import { api } from "@/lib/api";
import type { Conversation, Subject } from "@/lib/types";

type Group = { id: string; label: string; items: Conversation[] };
type GroupBy = "date" | "course";

const SEARCH_MIN = 2;

function groupByDate(items: Conversation[], t: TFunction, now = new Date()): Group[] {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = 86_400_000;
  const buckets: Group[] = [
    { id: "today", label: t("cw.group.today"), items: [] },
    { id: "yesterday", label: t("cw.group.yesterday"), items: [] },
    { id: "week", label: t("cw.group.week"), items: [] },
    { id: "older", label: t("cw.group.older"), items: [] },
  ];
  for (const item of items) {
    const at = new Date(item.updated_at).getTime();
    const index = at >= startOfToday ? 0 : at >= startOfToday - day ? 1 : at >= startOfToday - 7 * day ? 2 : 3;
    buckets[index].items.push(item);
  }
  return buckets.filter((bucket) => bucket.items.length > 0);
}

/** One group per course (courses A to Z), chats without a course last. */
function groupByCourse(items: Conversation[], subjects: Subject[], t: TFunction): Group[] {
  const byId = new Map<string, Group>();
  const none: Group = { id: "none", label: t("cw.noCourse"), items: [] };
  for (const item of items) {
    const subject = subjects.find((s) => s.id === item.subject_id);
    if (!subject) {
      none.items.push(item);
      continue;
    }
    const group = byId.get(subject.id) ?? { id: subject.id, label: subject.name, items: [] };
    group.items.push(item);
    byId.set(subject.id, group);
  }
  const groups = [...byId.values()].sort((a, b) => a.label.localeCompare(b.label));
  return none.items.length > 0 ? [...groups, none] : groups;
}

/** The student's conversations: searchable, grouped by recency, optionally narrowed to the
 *  current course, with rename and delete on each row. */
export function HistoryPane({
  conversations,
  loading,
  activeId,
  subjects,
  courseId,
  onSelect,
  onNew,
  onDelete,
  onRename,
}: {
  conversations: Conversation[];
  loading: boolean;
  activeId: string | null;
  subjects: Subject[];
  /** The course picked in the sidebar, if any. */
  courseId: string | null;
  onSelect: (conversation: Conversation) => void;
  onNew: () => void;
  onDelete: (conversation: Conversation) => void;
  onRename: (conversation: Conversation, title: string) => Promise<void>;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [onlyCourse, setOnlyCourse] = useState(courseId !== null);
  const [groupBy, setGroupBy] = useState<GroupBy>("date");
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  // Results of searching the text of every conversation (the server looks inside the messages).
  const [found, setFound] = useState<Conversation[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchFailed, setSearchFailed] = useState(false);

  const needle = query.trim();
  const serverSearch = needle.length >= SEARCH_MIN;

  useEffect(() => {
    if (!serverSearch) {
      setFound(null);
      setSearching(false);
      setSearchFailed(false);
      return;
    }
    let live = true;
    setSearching(true);
    const timer = window.setTimeout(() => {
      api<Conversation[]>(`/conversations?q=${encodeURIComponent(needle)}`)
        .then((rows) => {
          if (!live) return;
          setFound(rows);
          setSearchFailed(false);
        })
        .catch(() => {
          if (live) setSearchFailed(true);
        })
        .finally(() => {
          if (live) setSearching(false);
        });
    }, 280);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [needle, serverSearch]);

  const subjectName = (id: string | null) => subjects.find((s) => s.id === id)?.name ?? null;

  const visible = useMemo(() => {
    // While the search is running, the titles already loaded are filtered at once.
    const base = serverSearch && found ? found : conversations;
    const lowered = needle.toLowerCase();
    return base.filter(
      (c) =>
        (!onlyCourse || !courseId || c.subject_id === courseId) &&
        (!needle || (serverSearch && found ? true : c.title.toLowerCase().includes(lowered))),
    );
  }, [conversations, found, needle, serverSearch, onlyCourse, courseId]);
  const groups = useMemo(
    () => (groupBy === "course" ? groupByCourse(visible, subjects, t) : groupByDate(visible, t)),
    [visible, groupBy, subjects, t],
  );

  async function commitRename() {
    if (!renaming) return;
    const target = conversations.find((c) => c.id === renaming.id);
    const title = renaming.title.trim();
    setRenaming(null);
    if (target && title && title !== target.title) await onRename(target, title);
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 border-b border-border p-2.5">
        <Button variant="primary" className="w-full" onClick={onNew}>
          <MessageSquarePlus className="h-3.5 w-3.5" aria-hidden />
          {t("chat.new")}
        </Button>
        <label className="relative block">
          <span className="sr-only">{t("cw.search")}</span>
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("cw.search")}
            className="h-10 w-full rounded-xl border border-border bg-surface-2/60 pl-8 pr-2 text-[13px] placeholder:text-faint focus:border-primary focus:outline-none"
          />
        </label>
        {courseId ? (
          <div role="group" aria-label={t("cw.history")} className="flex rounded-xl bg-surface-3/70 p-0.5 text-xs">
            {[
              { value: true, label: t("cw.filterCourse") },
              { value: false, label: t("cw.filterAll") },
            ].map((option) => (
              <button
                key={String(option.value)}
                type="button"
                aria-pressed={onlyCourse === option.value}
                onClick={() => setOnlyCourse(option.value)}
                className={clsx(
                  "h-6 flex-1 rounded-lg font-medium",
                  onlyCourse === option.value ? "bg-primary-soft text-brand ring-1 ring-primary/30" : "text-muted hover:text-ink",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        ) : null}
        <div role="group" aria-label={t("chx.group.by")} className="flex rounded-xl bg-surface-3/70 p-0.5 text-xs">
          {[
            { value: "date" as const, label: t("chx.group.date") },
            { value: "course" as const, label: t("chx.group.course") },
          ].map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={groupBy === option.value}
              onClick={() => setGroupBy(option.value)}
              className={clsx(
                "h-6 flex-1 rounded-lg font-medium",
                groupBy === option.value ? "bg-primary-soft text-brand ring-1 ring-primary/30" : "text-muted hover:text-ink",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        {loading ? (
          <div className="space-y-2 p-3" aria-hidden>
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-9 animate-pulse rounded bg-surface-2" />
            ))}
          </div>
        ) : searchFailed ? (
          <p className="px-3.5 py-4 text-[13px] text-danger">{t("chx.search.failed")}</p>
        ) : visible.length === 0 ? (
          <p className="px-3.5 py-4 text-[13px] text-muted">
            {searching ? t("common.loading") : needle ? t("cw.searchNone", { q: needle }) : t("chat.noChats")}
          </p>
        ) : (
          groups.map((group) => (
            <section key={group.id} aria-label={group.label}>
              <h3 className="px-3.5 pb-1 pt-2.5 text-[10px] font-semibold uppercase tracking-wider text-faint rtl:tracking-normal">
                {group.label}
              </h3>
              <ul>
                {group.items.map((conversation) => {
                  const active = conversation.id === activeId;
                  const editing = renaming?.id === conversation.id;
                  return (
                    <li key={conversation.id} className="group relative">
                      {editing ? (
                        <form
                          className="flex items-center gap-1 px-2 py-1"
                          onSubmit={(event) => {
                            event.preventDefault();
                            void commitRename();
                          }}
                        >
                          <input
                            autoFocus
                            value={renaming.title}
                            maxLength={120}
                            onChange={(event) => setRenaming({ id: conversation.id, title: event.target.value })}
                            onKeyDown={(event) => event.key === "Escape" && setRenaming(null)}
                            aria-label={t("cw.rename")}
                            className="h-7 min-w-0 flex-1 rounded border border-primary bg-surface px-1.5 text-[13px] focus:outline-none"
                          />
                          <button type="submit" aria-label={t("common.save")} className="rounded p-1 text-brand hover:bg-surface-3">
                            <Check className="h-3.5 w-3.5" aria-hidden />
                          </button>
                          <button
                            type="button"
                            onClick={() => setRenaming(null)}
                            aria-label={t("common.cancel")}
                            className="rounded p-1 text-muted hover:bg-surface-3"
                          >
                            <X className="h-3.5 w-3.5" aria-hidden />
                          </button>
                        </form>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => onSelect(conversation)}
                            aria-current={active ? "true" : undefined}
                            className={clsx(
                              "mx-2 block w-[calc(100%-1rem)] rounded-xl px-3 py-2 text-left transition-colors hover:bg-surface-3/50",
                              active ? "bg-primary-soft ring-1 ring-primary/25" : "",
                            )}
                          >
                            <span className={clsx("block truncate pr-12 text-[13px]", active && "font-medium")}>
                              {conversation.title}
                            </span>
                            <span className="block truncate text-[11px] text-faint">
                              {subjectName(conversation.subject_id) ?? t("cw.noCourse")}
                            </span>
                            {serverSearch && conversation.match ? (
                              <span className="mt-0.5 block truncate text-[11px] italic text-muted">
                                {conversation.match}
                              </span>
                            ) : null}
                          </button>
                          <span className="absolute right-1.5 top-1.5 flex opacity-0 focus-within:opacity-100 group-hover:opacity-100">
                            <button
                              type="button"
                              onClick={() => setRenaming({ id: conversation.id, title: conversation.title })}
                              aria-label={`${t("cw.rename")}: ${conversation.title}`}
                              className="rounded p-1 text-muted hover:bg-surface-3 hover:text-ink"
                            >
                              <Pencil className="h-3.5 w-3.5" aria-hidden />
                            </button>
                            <button
                              type="button"
                              onClick={() => onDelete(conversation)}
                              aria-label={`${t("chat.deleteChat")}: ${conversation.title}`}
                              className="rounded p-1 text-muted hover:bg-surface-3 hover:text-danger"
                            >
                              <Trash2 className="h-3.5 w-3.5" aria-hidden />
                            </button>
                          </span>
                        </>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          ))
        )}
      </div>
    </div>
  );
}
