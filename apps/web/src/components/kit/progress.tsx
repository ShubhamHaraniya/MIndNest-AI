import clsx from "clsx";

/** A thin bar: 4 px, flat, no animation beyond the width change. */
export function ProgressBar({
  value,
  label,
  tone = "brand",
  className,
}: {
  /** 0..1 */
  value: number;
  label: string;
  tone?: "brand" | "success" | "warning" | "danger";
  className?: string;
}) {
  const pct = Math.max(0, Math.min(1, value));
  const fill = { brand: "bg-primary", success: "bg-success", warning: "bg-warning", danger: "bg-danger" }[tone];
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct * 100)}
      className={clsx("h-1.5 w-full overflow-hidden rounded-full bg-surface-3", className)}
    >
      <div className={clsx("h-full transition-[width] duration-500", fill)} style={{ width: `${pct * 100}%` }} />
    </div>
  );
}

/** A small ring with a number in the middle. */
export function ProgressRing({
  value,
  size = 56,
  stroke = 5,
  label,
  children,
}: {
  value: number;
  size?: number;
  stroke?: number;
  label: string;
  children?: React.ReactNode;
}) {
  const pct = Math.max(0, Math.min(1, value));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div
      role="img"
      aria-label={`${label}: ${Math.round(pct * 100)}%`}
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--primary)"
          strokeWidth={stroke}
          strokeDasharray={c}
          strokeDashoffset={c * (1 - pct)}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center text-center">{children}</div>
    </div>
  );
}
