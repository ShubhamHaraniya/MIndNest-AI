import clsx from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

/** A rounded panel with a thin border and a very soft shadow. */
export function Card({
  className,
  interactive = false,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return (
    <div
      className={clsx("glass rounded-card", interactive && "card-hover spot", className)}
      {...rest}
    />
  );
}

export function CardHeader({
  title,
  description,
  action,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("flex items-start justify-between gap-3", className)}>
      <div className="min-w-0">
        <h2 className="font-display text-base leading-tight">{title}</h2>
        {description ? <p className="mt-1 text-xs text-muted">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
