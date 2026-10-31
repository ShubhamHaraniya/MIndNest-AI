"use client";

import clsx from "clsx";
import { ExternalLink, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { ChatWorkspace } from "@/components/chat/workspace";
import { useT } from "@/i18n/client";
import type { Subject } from "@/lib/types";

/** "Ask AI" from any page: a button in the corner opens the chat in a side panel, so a student can
 *  ask about the page they are on without leaving it. The conversation is the same one the Chat
 *  page uses (history, sources, scope), and it is kept while the panel is closed. Ctrl/Cmd+J
 *  opens and closes it. It is not shown on the Chat page itself. */
export function AskAiPanel({ subjects, courseId }: { subjects: Subject[]; courseId: string | null }) {
  const t = useT();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  // The workspace is only mounted once the panel has been opened, then kept so nothing is lost.
  const [mounted, setMounted] = useState(false);

  const onChat = pathname === "/chat" || pathname.startsWith("/chat/");

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "j") {
        event.preventDefault();
        setOpen((value) => !value);
        setMounted(true);
      }
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (onChat) return null;

  return (
    <>
      {open ? null : (
        <button
          type="button"
          onClick={() => {
            setMounted(true);
            setOpen(true);
          }}
          aria-keyshortcuts="Control+J Meta+J"
          className="fixed bottom-20 right-4 z-30 flex h-11 items-center gap-2 rounded-full bg-primary px-4 text-sm font-semibold text-on-primary shadow-glow ring-1 ring-inset ring-white/25 transition-colors hover:bg-primary-hover lg:bottom-4 lg:right-5"
        >
          <Sparkles className="h-4 w-4" aria-hidden />
          {t("ask.button")}
        </button>
      )}

      <aside
        aria-label={t("ask.title")}
        aria-hidden={!open}
        className={clsx(
          "glass-strong fixed inset-y-0 right-0 z-40 flex w-full max-w-[28rem] flex-col rounded-l-3xl transition-transform duration-200 ease-out sm:w-[28rem]",
          open ? "translate-x-0" : "pointer-events-none invisible translate-x-full",
        )}
      >
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-4">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-soft text-brand">
            <Sparkles className="h-4 w-4" aria-hidden />
          </span>
          <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{t("ask.title")}</h2>
          <Link
            href="/chat"
            onClick={() => setOpen(false)}
            title={t("ask.openFull")}
            aria-label={t("ask.openFull")}
            className="rounded-lg p-2 text-muted hover:bg-surface-3 hover:text-ink"
          >
            <ExternalLink className="h-4 w-4" aria-hidden />
          </Link>
          <button
            type="button"
            onClick={() => setOpen(false)}
            title={t("common.close")}
            aria-label={t("common.close")}
            className="rounded-lg p-2 text-muted hover:bg-surface-3 hover:text-ink"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </header>
        <div className="min-h-0 flex-1">
          {mounted ? <ChatWorkspace embedded subjects={subjects} initialConversationId={null} courseId={courseId} /> : null}
        </div>
      </aside>
    </>
  );
}
