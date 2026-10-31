"use client";

import { motion } from "motion/react";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

/** A short fade and lift whenever the page changes. (No CSS filter here: a filtered ancestor would stop
 *  the glass panels inside from seeing the aurora behind them.) Keyed by path, so moving between tabs of one
 *  page (which only change the query) does not replay it. */
export function PageTransition({ children, className }: { children: ReactNode; className?: string }) {
  const pathname = usePathname();
  return (
    <motion.div
      key={pathname}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.38, ease: [0.22, 1, 0.36, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  );
}
