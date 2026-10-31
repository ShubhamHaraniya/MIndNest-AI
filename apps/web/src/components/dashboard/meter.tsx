"use client";

import clsx from "clsx";
import { motion } from "motion/react";

/** A thin bar whose fill grows from the left the first time it is seen. `value` is 0..1. */
export function Meter({
  value,
  tone = "primary",
  label,
  className,
}: {
  value: number;
  tone?: "primary" | "danger" | "warning" | "accent";
  label: string;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(1, value));
  const fill = {
    primary: "from-primary to-accent",
    accent: "from-accent to-primary",
    danger: "from-danger to-warning",
    warning: "from-warning to-danger",
  }[tone];
  return (
    <div
      role="img"
      aria-label={`${label}: ${Math.round(pct * 100)}%`}
      className={clsx("h-1.5 w-full overflow-hidden rounded-full bg-surface-3", className)}
    >
      <motion.div
        className={clsx("h-full origin-left rounded-full bg-gradient-to-r", fill)}
        initial={{ width: 0 }}
        whileInView={{ width: `${pct * 100}%` }}
        viewport={{ once: true }}
        transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
      />
    </div>
  );
}
