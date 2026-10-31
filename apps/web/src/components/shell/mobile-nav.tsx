"use client";

import clsx from "clsx";
import { Home, ListChecks, MessageSquare, Menu, BookOpen, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

import { Brand } from "@/components/brand";
import { CourseSwitcher } from "@/components/shell/course-switcher";
import { SidebarNav, isActive } from "@/components/shell/sidebar-nav";
import { useT } from "@/i18n/client";
import type { MessageKey } from "@/i18n/translate";
import type { Subject } from "@/lib/types";

/** The sidebar is hidden below the lg breakpoint; phones get the same grouped links in a drawer. */
export function MobileDrawer({
  open,
  onClose,
  isAdmin,
  subjects,
  currentCourse,
}: {
  open: boolean;
  onClose: () => void;
  isAdmin: boolean;
  subjects: Subject[];
  currentCourse: string | null;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const pathname = usePathname();
  const t = useT();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  // Following a link closes the drawer.
  useEffect(() => {
    onClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
      aria-label={t("nav.main")}
      className="glass-dialog m-0 mr-auto h-dvh max-h-none w-[18rem] max-w-[85vw] overflow-y-auto rounded-r-3xl p-0 text-ink"
    >
      {open ? (
        <div className="flex min-h-full flex-col">
          <div className="flex items-center justify-between px-5 py-4">
            <Brand href="/dashboard" />
            <button type="button" onClick={onClose} aria-label={t("common.close")} className="rounded-lg p-1.5 text-muted hover:bg-surface-3">
              <X className="h-5 w-5" aria-hidden />
            </button>
          </div>
          <div className="px-3 pb-3">
            <CourseSwitcher subjects={subjects} currentId={currentCourse} />
          </div>
          <div className="flex-1 px-3 pb-8">
            <SidebarNav isAdmin={isAdmin} onNavigate={onClose} />
          </div>
        </div>
      ) : null}
    </dialog>
  );
}

const TABS: { href: string; match: string[]; label: MessageKey; icon: typeof Home }[] = [
  { href: "/dashboard", match: ["/dashboard"], label: "nav.hub.home", icon: Home },
  { href: "/subjects", match: ["/subjects", "/quizzes"], label: "nav.hub.study", icon: BookOpen },
  { href: "/chat", match: ["/chat"], label: "nav.chat", icon: MessageSquare },
  { href: "/planner", match: ["/planner", "/calendar", "/assignments"], label: "nav.hub.plan", icon: ListChecks },
];

/** A thumb-reach tab bar on small screens: Home, Study, Chat and Plan, plus "More" for the rest. */
export function BottomBar({ onMore }: { onMore: () => void }) {
  const pathname = usePathname();
  const t = useT();
  const item = "flex min-w-0 flex-1 flex-col items-center gap-0.5 px-1 py-2 text-[11px] font-medium transition-colors";
  return (
    <nav aria-label={t("nav.bottom")} className="glass fixed inset-x-3 bottom-3 z-30 flex rounded-2xl pb-[env(safe-area-inset-bottom)] lg:hidden">
      {TABS.map(({ href, match, label, icon: Icon }) => {
        const active = match.some((prefix) => isActive(pathname, prefix));
        return (
          <Link key={href} href={href} aria-current={active ? "page" : undefined} className={clsx(item, active ? "text-brand" : "text-muted")}>
            <Icon className="h-[18px] w-[18px]" aria-hidden />
            <span className="max-w-full truncate">{t(label)}</span>
          </Link>
        );
      })}
      <button type="button" onClick={onMore} className={clsx(item, "text-muted")}>
        <Menu className="h-[18px] w-[18px]" aria-hidden />
        <span className="max-w-full truncate">{t("nav.more")}</span>
      </button>
    </nav>
  );
}
