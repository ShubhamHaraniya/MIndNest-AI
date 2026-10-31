"use client";

import clsx from "clsx";
import { useId, type ReactNode } from "react";

/** A small label on hover and keyboard focus. The text is also wired to the child with
 *  aria-describedby, so screen readers read it. Keep it to a few words. */
export function Tooltip({
  label,
  children,
  side = "bottom",
  className,
}: {
  label: string;
  children: ReactNode;
  side?: "top" | "bottom";
  className?: string;
}) {
  const id = useId();
  return (
    <span className={clsx("group/tip relative inline-flex", className)} aria-describedby={id}>
      {children}
      <span
        id={id}
        role="tooltip"
        className={clsx(
          "pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 whitespace-nowrap rounded bg-ink px-2 py-1 text-xs font-medium text-bg opacity-0 transition-opacity duration-150",
          "group-hover/tip:opacity-100 group-focus-within/tip:opacity-100",
          side === "bottom" ? "top-full mt-2" : "bottom-full mb-2",
        )}
      >
        {label}
      </span>
    </span>
  );
}
