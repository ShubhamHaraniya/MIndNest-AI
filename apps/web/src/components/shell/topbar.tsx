"use client";

import { Menu, Search } from "lucide-react";
import { useEffect, useState } from "react";

import { CommandPalette } from "@/components/shell/command-palette";
import { Breadcrumbs } from "@/components/shell/breadcrumbs";
import { BottomBar, MobileDrawer } from "@/components/shell/mobile-nav";
import { NotificationsMenu } from "@/components/shell/notifications-menu";
import { ProfileMenu } from "@/components/shell/profile-menu";
import { useT } from "@/i18n/client";
import type { Subject, User } from "@/lib/types";

export function Topbar({ user, subjects, currentCourse }: { user: User; subjects: Subject[]; currentCourse: string | null }) {
  const t = useT();
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);
  const [mac, setMac] = useState(false);

  useEffect(() => {
    setMac(/Mac|iPhone|iPad/.test(navigator.platform));
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPalette((open) => !open);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <header className="relative z-30 shrink-0 px-3 pt-3 sm:px-6">
        <div className="glass flex h-14 items-center gap-3 rounded-2xl px-3 sm:px-4">
        <button
          type="button"
          onClick={() => setDrawer(true)}
          aria-label={t("nav.menu")}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-ink hover:bg-surface-3 lg:hidden"
        >
          <Menu className="h-[18px] w-[18px]" aria-hidden />
        </button>
        <div className="hidden min-w-0 flex-1 md:block">
          <Breadcrumbs />
        </div>

        <div className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setPalette(true)}
            aria-label={t("palette.open")}
            aria-keyshortcuts="Control+K Meta+K"
            className="flex h-10 items-center gap-2 rounded-xl border border-border bg-surface-2/50 px-3 text-[13px] text-muted transition-colors hover:border-border-strong hover:text-ink md:w-72"
          >
            <Search className="h-4 w-4 shrink-0" aria-hidden />
            <span className="hidden min-w-0 flex-1 truncate text-left md:block">{t("palette.placeholder")}</span>
            <kbd className="hidden rounded-md border border-border bg-surface-3/70 px-1.5 py-px text-[10px] font-medium md:block">
              {mac ? "⌘K" : "Ctrl K"}
            </kbd>
          </button>
          <NotificationsMenu />
          <ProfileMenu user={user} />
        </div>
        </div>
      </header>

      <MobileDrawer open={drawer} onClose={() => setDrawer(false)} isAdmin={user.is_admin} subjects={subjects} currentCourse={currentCourse} />
      <BottomBar onMore={() => setDrawer(true)} />
      <CommandPalette open={palette} onClose={() => setPalette(false)} isAdmin={user.is_admin} />
    </>
  );
}
