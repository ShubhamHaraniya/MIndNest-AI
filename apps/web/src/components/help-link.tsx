"use client";

import { CircleHelp } from "lucide-react";
import Link from "next/link";

import { useT } from "@/i18n/client";

/** A small "Help with this page" link that opens the matching part of the student guide. */
export function HelpLink({ section }: { section: string }) {
  const t = useT();
  return (
    <Link
      href={`/guide#${section}`}
      className="inline-flex h-9 items-center gap-1.5 rounded-xl px-2.5 text-[13px] text-muted hover:bg-surface-3/70 hover:text-ink"
    >
      <CircleHelp className="h-4 w-4" aria-hidden />
      {t("gx.help.here")}
    </Link>
  );
}
