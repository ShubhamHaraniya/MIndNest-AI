"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { PageTransition } from "@/components/motion/page-transition";
import { HubTabs } from "@/components/shell/hub-tabs";

/** The scrolling area under the top bar. Most pages are a centred column; the chat workspace
 *  needs the whole area, with its own panes scrolling, so it is not padded or centred. */
export function PageFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const full = pathname === "/chat" || pathname.startsWith("/chat/");
  if (full) {
    return (
      <main id="main" className="min-h-0 flex-1 pb-12 lg:pb-0">
        <PageTransition className="h-full">{children}</PageTransition>
      </main>
    );
  }
  return (
    <main id="main" className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[1240px] px-4 py-6 pb-24 sm:px-8 lg:pb-12">
        <HubTabs />
        <PageTransition>{children}</PageTransition>
      </div>
    </main>
  );
}
