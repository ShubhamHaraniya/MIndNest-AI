import clsx from "clsx";
import Link from "next/link";
import type { ReactNode } from "react";

/** A titled working area: a thin border, a compact header row with an optional link or control,
 *  and a body that is normally a list or table running edge to edge. */
export function Panel({
  title,
  description,
  action,
  footer,
  children,
  className,
  bodyClassName,
  id,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  id?: string;
}) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section aria-labelledby={headingId} className={clsx("glass rounded-card", className)}>
      <header className="flex min-h-12 items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <div className="min-w-0">
          <h2 id={headingId} className="truncate text-sm font-semibold leading-5">
            {title}
          </h2>
          {description ? <p className="truncate text-xs text-muted">{description}</p> : null}
        </div>
        {action ? <div className="shrink-0 text-xs">{action}</div> : null}
      </header>
      <div className={bodyClassName}>{children}</div>
      {footer ? <footer className="border-t border-border px-3.5 py-2 text-xs text-muted">{footer}</footer> : null}
    </section>
  );
}

/** The small "View all" style link used in panel headers. */
export function PanelLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="font-medium text-brand underline-offset-2 hover:underline">
      {children}
    </Link>
  );
}

/** Label/value pairs in a tight grid; for facts about one thing (a course, a file). */
export function Facts({ items, className }: { items: { label: string; value: ReactNode }[]; className?: string }) {
  return (
    <dl className={clsx("grid gap-x-6 gap-y-2", className)}>
      {items.map((item) => (
        <div key={item.label} className="min-w-0">
          <dt className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{item.label}</dt>
          <dd className="tabular truncate text-[13px] text-ink">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
