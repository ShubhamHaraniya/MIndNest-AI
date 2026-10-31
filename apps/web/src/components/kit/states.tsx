"use client";

import clsx from "clsx";
import { AlertTriangle, Inbox, Lock, SearchX, type LucideIcon } from "lucide-react";
import { createElement, isValidElement, type ReactElement, type ReactNode } from "react";

import { Button, ButtonLink } from "@/components/kit/button";
import { useT } from "@/i18n/client";

/** A Lucide component (from a client component) or an already-made element (from a server component:
 *  a component function cannot cross from server to client, an element can). */
type StateIcon = LucideIcon | ReactElement;

function StateShell({
  icon,
  tone,
  title,
  description,
  children,
  compact,
  role,
}: {
  icon: StateIcon;
  tone: string;
  title: string;
  description?: string;
  children?: ReactNode;
  compact?: boolean;
  role?: "alert" | "status";
}) {
  return (
    <section
      role={role}
      className={clsx(
        "flex flex-col items-center rounded-card border border-dashed border-border-strong bg-surface/60 text-center",
        compact ? "px-6 py-8" : "px-6 py-12",
      )}
    >
      <span className={clsx("flex h-11 w-11 items-center justify-center rounded-xl", tone)}>
        {isValidElement(icon)
          ? icon
          : createElement(icon as LucideIcon, { className: "h-[18px] w-[18px]", "aria-hidden": true })}
      </span>
      <h2 className="font-display mt-3 text-base">{title}</h2>
      {description ? <p className="mt-1.5 max-w-md text-sm text-muted">{description}</p> : null}
      {children ? <div className="mt-4 flex flex-wrap justify-center gap-2">{children}</div> : null}
    </section>
  );
}

/** Nothing here yet: says what this place is for and offers the first step. */
export function EmptyState({
  title,
  description,
  icon = Inbox,
  children,
  compact,
}: {
  title: string;
  description?: string;
  icon?: StateIcon;
  children?: ReactNode;
  compact?: boolean;
}) {
  return (
    <StateShell icon={icon} tone="bg-primary-soft text-brand" title={title} description={description} compact={compact}>
      {children}
    </StateShell>
  );
}

export function NoResults({ title, description, children }: { title: string; description?: string; children?: ReactNode }) {
  return (
    <StateShell icon={SearchX} tone="bg-surface-3 text-muted" title={title} description={description} compact>
      {children}
    </StateShell>
  );
}

/** Something went wrong. Always offers a way forward (retry, or a link). */
export function ErrorState({
  title,
  description,
  onRetry,
  compact,
  children,
}: {
  title?: string;
  description?: string;
  onRetry?: () => void;
  compact?: boolean;
  children?: ReactNode;
}) {
  const t = useT();
  return (
    <StateShell
      role="alert"
      icon={AlertTriangle}
      tone="bg-danger-soft text-danger"
      title={title ?? t("state.errorTitle")}
      description={description ?? t("state.errorBody")}
      compact={compact}
    >
      {onRetry ? <Button onClick={onRetry}>{t("common.retry")}</Button> : null}
      {children}
    </StateShell>
  );
}

/** 403: signed in, but this belongs to someone else or needs a role the student does not have. */
export function PermissionDenied({ description }: { description?: string }) {
  const t = useT();
  return (
    <StateShell
      role="alert"
      icon={Lock}
      tone="bg-warning-soft text-warning"
      title={t("state.forbiddenTitle")}
      description={description ?? t("state.forbiddenBody")}
    >
      <ButtonLink href="/dashboard">{t("state.backToDashboard")}</ButtonLink>
    </StateShell>
  );
}
