import clsx from "clsx";
import type { HTMLAttributes } from "react";

export type Tone = "neutral" | "brand" | "success" | "warning" | "danger" | "info";

const TONES: Record<Tone, string> = {
  neutral: "bg-surface-3 text-muted",
  brand: "bg-primary-soft text-brand",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  info: "bg-info-soft text-info",
};

/** A compact status tag: a soft pill, no outline. */
export function Badge({ tone = "neutral", className, ...rest }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2 py-px text-[11px] font-semibold leading-[18px]",
        TONES[tone],
        className,
      )}
      {...rest}
    />
  );
}
