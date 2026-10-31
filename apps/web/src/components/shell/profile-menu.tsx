"use client";

import { ChevronsUpDown, HelpCircle, LogOut, Settings, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Avatar } from "@/components/kit/avatar";
import { Popover } from "@/components/kit/popover";
import { ThemeToggle } from "@/components/kit/theme-toggle";
import { LocaleSwitcher } from "@/components/locale-switcher";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

const itemClass =
  "flex w-full items-center gap-3 rounded px-3 py-1.5 text-sm text-ink transition-colors hover:bg-surface-3";

export function ProfileMenu({ user }: { user: Pick<User, "display_name" | "email" | "is_admin"> }) {
  const t = useT();
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function signOut() {
    setBusy(true);
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <Popover
      label={t("shell.account")}
      panelClassName="w-72 p-2"
      trigger={({ open, toggle, id }) => (
        <button
          type="button"
          data-popover-trigger
          onClick={toggle}
          aria-expanded={open}
          aria-controls={open ? id : undefined}
          aria-label={t("shell.account")}
          className="flex items-center gap-1.5 rounded py-0.5 pl-0.5 pr-1.5 transition-colors hover:bg-surface-3"
        >
          <Avatar name={user.display_name} size="sm" />
          <ChevronsUpDown className="hidden h-4 w-4 text-faint sm:block" aria-hidden />
        </button>
      )}
    >
      {(close) => (
        <div>
          <div className="flex items-center gap-3 px-3 py-3">
            <Avatar name={user.display_name} size="md" />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{user.display_name}</p>
              <p className="truncate text-xs text-muted">{user.email}</p>
            </div>
          </div>
          <div className="my-1 border-t border-border" />
          <Link href="/settings" onClick={close} className={itemClass}>
            <Settings className="h-4 w-4 text-muted" aria-hidden />
            {t("nav.settings")}
          </Link>
          <Link href="/guide" onClick={close} className={itemClass}>
            <HelpCircle className="h-4 w-4 text-muted" aria-hidden />
            {t("nav.guide")}
          </Link>
          {user.is_admin ? (
            <Link href="/admin" onClick={close} className={itemClass}>
              <ShieldCheck className="h-4 w-4 text-muted" aria-hidden />
              {t("nav.admin")}
            </Link>
          ) : null}
          <div className="my-1 border-t border-border" />
          <div className="space-y-3 px-3 py-2">
            <ThemeToggle />
            <LocaleSwitcher persist />
          </div>
          <div className="my-1 border-t border-border" />
          <button type="button" onClick={() => void signOut()} disabled={busy} className={`${itemClass} text-danger disabled:opacity-60`}>
            <LogOut className="h-4 w-4" aria-hidden />
            {t("common.signOut")}
          </button>
        </div>
      )}
    </Popover>
  );
}
