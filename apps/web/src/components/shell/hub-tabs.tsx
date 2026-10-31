"use client";

import clsx from "clsx";
import { motion } from "motion/react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useT } from "@/i18n/client";
import { hubOf } from "@/lib/nav";

/** The pages of the current hub as one glass pill strip, so "Plan" (planner, calendar, assignments)
 *  or "Study" feels like a single place. The lit pill slides to the page you open. Shown on the
 *  hub's own pages, not on detail pages. */
export function HubTabs() {
  const pathname = usePathname();
  const t = useT();
  const found = hubOf(pathname);
  if (!found || found.items.length < 2) return null;
  // Only on the pages themselves (/planner), not on a detail page (/subjects/<id>) or in the chat.
  if (!found.items.some((item) => item.href === pathname) || pathname === "/chat") return null;

  return (
    <nav aria-label={t(found.hub.label)} className="glass mb-6 flex gap-1 overflow-x-auto rounded-2xl p-1 sm:inline-flex">
      {found.items.map((item) => {
        const active = item.href === pathname;
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={clsx(
              "relative inline-flex h-9 shrink-0 items-center gap-2 rounded-xl px-3.5 text-[13px] font-medium transition-colors",
              active ? "text-on-primary" : "text-muted hover:text-ink",
            )}
          >
            {active ? (
              <motion.span
                layoutId="hub-lit"
                aria-hidden
                className="absolute inset-0 rounded-xl bg-primary shadow-glow"
                transition={{ type: "spring", stiffness: 400, damping: 34 }}
              />
            ) : null}
            <Icon className="relative h-4 w-4" strokeWidth={1.75} aria-hidden />
            <span className="relative">{t(item.label)}</span>
          </Link>
        );
      })}
    </nav>
  );
}
