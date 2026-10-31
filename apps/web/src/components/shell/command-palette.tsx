"use client";

import clsx from "clsx";
import { CornerDownLeft, Loader2, Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { useT } from "@/i18n/client";
import type { MessageKey } from "@/i18n/translate";
import { api } from "@/lib/api";
import { NAV_ITEMS } from "@/lib/nav";
import type { SearchHit, SearchResults } from "@/lib/types";

type Row = { id: string; group: MessageKey; title: string; detail?: string | null; href: string; icon?: React.ElementType };

const RESULT_GROUPS: { field: keyof Omit<SearchResults, "query">; label: MessageKey }[] = [
  { field: "subjects", label: "palette.subjects" },
  { field: "materials", label: "palette.materials" },
  { field: "quizzes", label: "palette.quizzes" },
  { field: "assignments", label: "palette.assignments" },
  { field: "conversations", label: "palette.conversations" },
  { field: "exams", label: "palette.exams" },
];

const MIN_QUERY = 2;

/** Ctrl/Cmd+K search: jumps to any page and searches the student's own subjects, materials,
 *  quizzes, assignments, chats and exams on the server. */
export function CommandPalette({ open, onClose, isAdmin }: { open: boolean; onClose: () => void; isAdmin: boolean }) {
  const t = useT();
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [active, setActive] = useState(0);

  const trimmed = query.trim();
  const searching = trimmed.length >= MIN_QUERY;

  useEffect(() => {
    const el = dialog.current;
    if (!el) return;
    if (open && !el.open) {
      el.showModal();
      input.current?.focus();
    }
    if (!open && el.open) el.close();
    if (!open) {
      setQuery("");
      setResults(null);
      setFailed(false);
      setActive(0);
    }
  }, [open]);

  // Debounced server search; a newer keystroke cancels the request still in flight.
  useEffect(() => {
    if (!searching) {
      setResults(null);
      setLoading(false);
      setFailed(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    const timer = setTimeout(() => {
      api<SearchResults>(`/search?q=${encodeURIComponent(trimmed)}`, { signal: controller.signal })
        .then((data) => {
          setResults(data);
          setFailed(false);
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          void error;
          setFailed(true);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 220);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [trimmed, searching]);

  const rows = useMemo<Row[]>(() => {
    const needle = trimmed.toLowerCase();
    const pages: Row[] = NAV_ITEMS.filter((item) => isAdmin || !item.adminOnly)
      .map((item) => ({ item, label: t(item.label) }))
      .filter(({ label }) => !needle || label.toLowerCase().includes(needle))
      .map(({ item, label }) => ({
        id: `page:${item.href}`,
        group: "palette.pages" as MessageKey,
        title: label,
        detail: t(item.description),
        href: item.href,
        icon: item.icon,
      }));
    const found: Row[] = results
      ? RESULT_GROUPS.flatMap(({ field, label }) =>
          (results[field] as SearchHit[]).map((hit) => ({
            id: `${field}:${hit.id}`,
            group: label,
            title: hit.title,
            detail: hit.detail,
            href: hit.href,
          })),
        )
      : [];
    return [...found, ...pages];
  }, [results, trimmed, isAdmin, t]);

  useEffect(() => setActive(0), [rows.length, trimmed]);

  function go(row: Row | undefined) {
    if (!row) return;
    onClose();
    router.push(row.href);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => (rows.length ? (index + 1) % rows.length : 0));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => (rows.length ? (index - 1 + rows.length) % rows.length : 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(rows[active]);
    }
  }

  useEffect(() => {
    document.getElementById(`${listId}-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [active, listId]);

  let lastGroup: MessageKey | null = null;
  const empty = searching && !loading && !failed && results !== null && rows.length === 0;

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
      aria-label={t("palette.title")}
      className="m-0 mx-auto mt-[10vh] w-[calc(100%-1.5rem)] max-w-xl glass-dialog overflow-hidden rounded-2xl p-0 text-ink"
    >
      {open ? (
        <div onKeyDown={onKeyDown}>
          <div className="flex items-center gap-3 border-b border-border px-4">
            {loading ? (
              <Loader2 className="h-5 w-5 shrink-0 animate-spin text-brand" aria-hidden />
            ) : (
              <Search className="h-5 w-5 shrink-0 text-faint" aria-hidden />
            )}
            <input
              ref={input}
              role="combobox"
              aria-expanded
              aria-controls={listId}
              aria-activedescendant={rows.length ? `${listId}-${active}` : undefined}
              aria-autocomplete="list"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("palette.placeholder")}
              maxLength={80}
              className="h-12 min-w-0 flex-1 bg-transparent text-base outline-none focus-visible:outline-none placeholder:text-faint"
            />
            <button
              type="button"
              onClick={onClose}
              aria-label={t("common.close")}
              className="rounded-lg p-1.5 text-muted hover:bg-surface-3 hover:text-ink"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>

          <div className="max-h-[55vh] overflow-y-auto p-2">
            {failed ? (
              <p role="alert" className="px-3 py-6 text-center text-sm text-danger">
                {t("palette.failed")}
              </p>
            ) : null}
            {empty ? <p className="px-3 py-3 text-center text-sm text-muted">{t("palette.noResults", { query: trimmed })}</p> : null}
            {!searching && trimmed.length > 0 ? (
              <p className="px-3 pb-1 pt-2 text-xs text-faint">{t("palette.typeMore")}</p>
            ) : null}
            <ul id={listId} role="listbox" aria-label={t("palette.title")}>
              {rows.map((row, index) => {
                const header = row.group !== lastGroup;
                lastGroup = row.group;
                const Icon = row.icon;
                return (
                  <li key={row.id} role="presentation">
                    {header ? (
                      <p className="px-3 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wider text-faint">{t(row.group)}</p>
                    ) : null}
                    <div
                      id={`${listId}-${index}`}
                      role="option"
                      aria-selected={index === active}
                      onMouseMove={() => setActive(index)}
                      onClick={() => go(row)}
                      className={clsx(
                        "flex cursor-pointer items-center gap-3 rounded px-3 py-2",
                        index === active ? "bg-surface-3 text-ink" : "text-ink",
                      )}
                    >
                      {Icon ? <Icon className="h-4 w-4 shrink-0" aria-hidden /> : <Search className="h-4 w-4 shrink-0 text-faint" aria-hidden />}
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{row.title}</span>
                        {row.detail ? <span className="block truncate text-xs text-muted">{row.detail}</span> : null}
                      </span>
                      {index === active ? <CornerDownLeft className="h-4 w-4 shrink-0" aria-hidden /> : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>

          <p className="hidden border-t border-border bg-surface-2 px-4 py-2 text-xs text-faint sm:block">{t("palette.hint")}</p>
        </div>
      ) : null}
    </dialog>
  );
}
