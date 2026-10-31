"use client";

import { ChevronRight, Home } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useT } from "@/i18n/client";
import type { MessageKey } from "@/i18n/translate";
import { NAV_ITEMS } from "@/lib/nav";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const WORDS: Record<string, MessageKey> = {
  attempt: "crumb.attempt",
  datasets: "crumb.datasets",
  runs: "crumb.runs",
};

/** Home > Section > Details, worked out from the address. A segment that is an id shows as
 *  "Details" (the page itself carries the real name as its heading). */
export function Breadcrumbs() {
  const pathname = usePathname();
  const t = useT();
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length === 0) return null;

  const crumbs = parts.map((part, index) => {
    const href = "/" + parts.slice(0, index + 1).join("/");
    const item = NAV_ITEMS.find((candidate) => candidate.href === href);
    const key = item?.label ?? WORDS[part];
    const label = key ? t(key) : UUID.test(part) ? t("crumb.details") : decodeURIComponent(part);
    return { href, label };
  });

  return (
    <nav aria-label={t("crumb.label")} className="min-w-0">
      <ol className="flex min-w-0 items-center gap-1.5 text-[13px]">
        <li className="hidden shrink-0 sm:block">
          <Link href="/dashboard" aria-label={t("nav.dashboard")} className="text-faint transition-colors hover:text-ink">
            <Home className="h-3.5 w-3.5" aria-hidden />
          </Link>
        </li>
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          return (
            <li key={crumb.href} className={`flex min-w-0 items-center gap-1.5 ${last ? "" : "hidden sm:flex"}`}>
              <ChevronRight className="hidden h-3.5 w-3.5 shrink-0 text-faint sm:block" aria-hidden />
              {last ? (
                <span aria-current="page" className="truncate font-medium text-ink">{crumb.label}</span>
              ) : (
                <Link href={crumb.href} className="truncate text-muted transition-colors hover:text-ink">{crumb.label}</Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
