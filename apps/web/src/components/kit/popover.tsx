"use client";

import clsx from "clsx";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

/** A panel that opens under a trigger. Closes on Escape, on an outside click, and when focus
 *  leaves it. `children` may be a function to get a `close` callback (for menu items). */
export function Popover({
  trigger,
  children,
  align = "end",
  side = "bottom",
  label,
  panelClassName,
  onOpenChange,
}: {
  trigger: (props: { open: boolean; toggle: () => void; id: string }) => ReactNode;
  children: ReactNode | ((close: () => void) => ReactNode);
  align?: "start" | "end";
  side?: "bottom" | "top";
  label: string;
  panelClassName?: string;
  onOpenChange?: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const id = useId();

  function set(next: boolean) {
    setOpen(next);
    onOpenChange?.(next);
  }

  useEffect(() => {
    if (!open) return;
    function onPointer(event: PointerEvent) {
      if (root.current && !root.current.contains(event.target as Node)) set(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        set(false);
        root.current?.querySelector<HTMLElement>("[data-popover-trigger]")?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <div ref={root} className="relative" onBlur={(event) => {
      if (open && !event.currentTarget.contains(event.relatedTarget as Node | null)) set(false);
    }}>
      {trigger({ open, toggle: () => set(!open), id })}
      {open ? (
        <div
          id={id}
          role="dialog"
          aria-label={label}
          className={clsx(
            "glass-strong popover-panel absolute z-50 animate-pop-in rounded-2xl",
            side === "bottom" ? "top-full mt-2 origin-top" : "bottom-full mb-2 origin-bottom",
            align === "end" ? "right-0" : "left-0",
            panelClassName,
          )}
        >
          {typeof children === "function" ? children(() => set(false)) : children}
        </div>
      ) : null}
    </div>
  );
}
