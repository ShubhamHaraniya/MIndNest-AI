"use client";

import clsx from "clsx";
import { motion } from "motion/react";
import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";

export type TabItem<T extends string> = { id: T; label: ReactNode; count?: number };

/** Tabs with arrow-key, Home and End navigation. The caller owns the selected value and renders
 *  the panel, using `panelProps(id)` on it so the two stay linked for assistive technology. */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  label,
  className,
}: {
  items: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  label: string;
  className?: string;
}) {
  const base = useId();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function move(event: KeyboardEvent, index: number) {
    const last = items.length - 1;
    const next =
      event.key === "ArrowRight" ? (index === last ? 0 : index + 1)
      : event.key === "ArrowLeft" ? (index === 0 ? last : index - 1)
      : event.key === "Home" ? 0
      : event.key === "End" ? last
      : -1;
    if (next < 0) return;
    event.preventDefault();
    const item = items[next];
    onChange(item.id);
    refs.current[item.id]?.focus();
  }

  return (
    <div role="tablist" aria-label={label} className={clsx("glass flex gap-1 overflow-x-auto rounded-2xl p-1", className)}>
      {items.map((item, index) => {
        const selected = item.id === value;
        return (
          <button
            key={item.id}
            ref={(node) => {
              refs.current[item.id] = node;
            }}
            role="tab"
            id={`${base}-tab-${item.id}`}
            aria-selected={selected}
            aria-controls={`${base}-panel-${item.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(item.id)}
            onKeyDown={(event) => move(event, index)}
            className={clsx(
              "relative inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-xl px-3.5 py-2 text-sm font-semibold transition-colors",
              selected ? "text-brand" : "text-muted hover:text-ink",
            )}
          >
            {selected ? (
              <motion.span
                layoutId={`${base}-lit`}
                aria-hidden
                className="absolute inset-0 rounded-xl bg-primary-soft ring-1 ring-primary/30"
                transition={{ type: "spring", stiffness: 420, damping: 36 }}
              />
            ) : null}
            <span className="relative">{item.label}</span>
            {item.count !== undefined ? (
              <span className="tabular relative rounded-full bg-surface-3 px-2 text-xs text-muted">{item.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export function tabPanelProps(base: string, id: string) {
  return { role: "tabpanel" as const, id: `${base}-panel-${id}`, "aria-labelledby": `${base}-tab-${id}`, tabIndex: 0 };
}
