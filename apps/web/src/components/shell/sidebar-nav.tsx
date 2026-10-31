"use client";

import clsx from "clsx";
import { motion } from "motion/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useId } from "react";

import { useT } from "@/i18n/client";
import { HUBS, NAV_ITEMS } from "@/lib/nav";

export function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

const rowClass = "group relative flex h-10 items-center gap-3 rounded-xl px-3 text-[13.5px] transition-colors";

/** The five hubs, shared by the desktop sidebar and the mobile drawer. A hub with one page is a
 *  single row; a hub with several shows its pages underneath its name. The lit highlight slides
 *  from row to row as you move (shared layout animation). */
export function SidebarNav({ onNavigate }: { isAdmin?: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const t = useT();
  const scope = useId();

  return (
    <nav aria-label={t("nav.main")} className="space-y-5">
      {HUBS.map((hub) => {
        const items = NAV_ITEMS.filter((item) => item.group === hub.id);
        if (items.length === 0) return null;
        const single = items.length === 1;
        return (
          <div key={hub.id}>
            {single ? null : (
              <p className="mb-1.5 px-3 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-faint rtl:tracking-normal">{t(hub.label)}</p>
            )}
            <ul className="space-y-0.5">
              {items.map((item) => {
                const active = isActive(pathname, item.href);
                const Icon = single ? hub.icon : item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={clsx(rowClass, active ? "font-semibold text-ink" : "text-muted hover:bg-surface-3/60 hover:text-ink")}
                    >
                      {active ? (
                        <motion.span
                          layoutId={`nav-lit-${scope}`}
                          aria-hidden
                          className="absolute inset-0 rounded-xl border border-primary/30 bg-primary-soft shadow-glow"
                          transition={{ type: "spring", stiffness: 380, damping: 32 }}
                        />
                      ) : null}
                      <Icon
                        className={clsx("relative h-[18px] w-[18px] shrink-0 transition-colors", active ? "text-brand" : "text-faint group-hover:text-ink")}
                        strokeWidth={1.75}
                        aria-hidden
                      />
                      <span className="relative min-w-0 truncate">{single ? t(hub.label) : t(item.label)}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}
