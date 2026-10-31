"use client";

import { motion, useReducedMotion } from "motion/react";
import { useId, type ReactNode } from "react";

/** A progress ring that draws itself once and glows. `value` is 0..1; children sit in the middle. */
export function AnimatedRing({
  value,
  size = 64,
  stroke = 6,
  label,
  tone = "primary",
  children,
  className,
}: {
  value: number;
  size?: number;
  stroke?: number;
  label: string;
  tone?: "primary" | "success" | "warning" | "danger";
  children?: ReactNode;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const id = useId();
  const pct = Math.max(0, Math.min(1, value));
  const r = (size - stroke) / 2;
  const from = { primary: "var(--primary)", success: "var(--success)", warning: "var(--warning)", danger: "var(--danger)" }[tone];
  const to = tone === "primary" ? "var(--accent)" : from;
  return (
    <div
      role="img"
      aria-label={`${label}: ${Math.round(pct * 100)}%`}
      className={`relative inline-flex shrink-0 items-center justify-center ${className ?? ""}`}
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={from} />
            <stop offset="100%" stopColor={to} />
          </linearGradient>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke} />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={`url(#${id})`}
          strokeWidth={stroke}
          strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 5px ${from})` }}
          initial={{ pathLength: reduce ? pct : 0 }}
          whileInView={{ pathLength: pct }}
          viewport={{ once: true }}
          transition={{ duration: 1.1, ease: [0.22, 1, 0.36, 1] }}
        />
      </svg>
      {children ? <div className="absolute inset-0 flex items-center justify-center text-center">{children}</div> : null}
    </div>
  );
}
