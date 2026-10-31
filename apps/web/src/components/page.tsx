import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { HelpLink } from "@/components/help-link";
import { EmptyState as KitEmptyState } from "@/components/kit/states";

export function PageHeader({
  title,
  description,
  actions,
  help,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  /** The id of the student-guide section that explains this page; adds a "Help" link. */
  help?: string;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="font-display text-3xl leading-tight sm:text-[2.1rem]">{title}</h1>
        <span aria-hidden className="mt-2 block h-px w-16 bg-gradient-to-r from-primary to-transparent" />
        {description ? <p className="mt-2.5 max-w-2xl text-sm text-muted">{description}</p> : null}
      </div>
      {actions || help ? (
        <div className="flex flex-wrap items-center gap-2">
          {actions}
          {help ? <HelpLink section={help} /> : null}
        </div>
      ) : null}
    </header>
  );
}

// Same props as before so every existing screen picks up the new empty-state look; `icon` is new.
export function EmptyState({
  title,
  description,
  icon,
  children,
}: {
  title: string;
  description: string;
  icon?: LucideIcon;
  children?: ReactNode;
}) {
  return (
    <KitEmptyState title={title} description={description} icon={icon}>
      {children}
    </KitEmptyState>
  );
}
