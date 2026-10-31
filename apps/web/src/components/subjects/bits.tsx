"use client";

import clsx from "clsx";
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { Badge, type Tone } from "@/components/kit/badge";
import { ProgressBar } from "@/components/kit/progress";
import { Th } from "@/components/kit/table";
import { useT } from "@/i18n/client";
import type { TFunction } from "@/i18n/translate";
import { percent } from "@/lib/format";
import type { Material } from "@/lib/types";

import { INGEST_ERROR_KEYS, STAGE_KEYS, STAGE_ORDER, isStale, isWorking } from "./model";

const ICON_BUTTON =
  "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-muted hover:bg-surface-3 hover:text-ink disabled:pointer-events-none disabled:opacity-40";

/** A square icon-only button. The label is both the accessible name and the hover title. */
export function IconButton({
  label,
  danger,
  className,
  children,
  ...rest
}: { label: string; danger?: boolean; children: ReactNode } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, "title" | "aria-label">) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={clsx(ICON_BUTTON, danger && "hover:text-danger", className)}
      {...rest}
    >
      {children}
    </button>
  );
}

export function IconLink({
  label,
  href,
  className,
  children,
  download,
}: {
  label: string;
  href: string;
  className?: string;
  children: ReactNode;
  download?: boolean;
}) {
  const classes = clsx(ICON_BUTTON, className);
  return download ? (
    <a href={href} aria-label={label} title={label} className={classes}>
      {children}
    </a>
  ) : (
    <Link href={href} aria-label={label} title={label} className={classes}>
      {children}
    </Link>
  );
}

export function microLabel(extra?: string): string {
  return clsx("text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal", extra);
}

/** A column header that sorts when pressed. */
export function SortTh({
  label,
  active,
  dir,
  onSort,
  className,
  align,
}: {
  label: string;
  active: boolean;
  dir: "asc" | "desc";
  onSort: () => void;
  className?: string;
  align?: "left" | "right";
}) {
  return (
    <Th className={className} align={align} aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}>
      <button
        type="button"
        onClick={onSort}
        className={clsx("inline-flex items-center gap-1 uppercase tracking-wide hover:text-ink rtl:tracking-normal", active && "text-ink")}
      >
        {label}
        {active ? (
          dir === "asc" ? <ChevronUp className="h-3 w-3" aria-hidden /> : <ChevronDown className="h-3 w-3" aria-hidden />
        ) : (
          <span className="h-3 w-3" aria-hidden />
        )}
      </button>
    </Th>
  );
}

/** Quiz accuracy for a document or module: a thin bar and the number, red when it needs revision. */
export function AccuracyCell({
  accuracy,
  answers,
  weak,
  label,
  className,
}: {
  accuracy: number | null;
  answers: number;
  weak: boolean;
  label: string;
  className?: string;
}) {
  const t = useT();
  if (accuracy === null || answers === 0) {
    return (
      <span className="text-faint" title={t("sj.progress.notPractised")}>
        —
      </span>
    );
  }
  const tone = weak ? "danger" : accuracy >= 0.8 ? "success" : "warning";
  return (
    <span className={clsx("flex shrink-0 items-center gap-2", className)} title={t("sj.progress.answers", { count: answers })}>
      <span className="block w-12 shrink-0">
        <ProgressBar value={accuracy} label={label} tone={tone} />
      </span>
      <span className={clsx("tabular w-9 text-right text-[13px]", weak && "font-medium text-danger")}>{percent(accuracy)}</span>
    </span>
  );
}

/** What a file is doing right now: ready, a step of the reading pipeline, or why it failed. */
export function statusLabel(t: TFunction, material: Pick<Material, "status" | "stage">): string {
  if (material.status === "processing" && material.stage && STAGE_KEYS[material.stage]) return t(STAGE_KEYS[material.stage]);
  return t(`materials.status.${material.status}`);
}

export function failureReason(t: TFunction, material: Pick<Material, "status" | "error">): string | null {
  if (material.status !== "failed") return null;
  return t(material.error ? (INGEST_ERROR_KEYS[material.error] ?? "materials.error.internal") : "materials.error.internal");
}

export function StatusCell({ material }: { material: Material }) {
  const t = useT();
  const working = isWorking(material);
  const stale = isStale(material);
  const step = material.stage ? STAGE_ORDER.indexOf(material.stage) : -1;
  return (
    <span className="inline-flex min-w-0 flex-col gap-1">
      <Badge tone={material.status === "ready" ? "success" : material.status === "failed" ? "danger" : stale ? "warning" : "info"}>
        {working ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : null}
        <span className="truncate">{statusLabel(t, material)}</span>
      </Badge>
      {material.status === "processing" && step >= 0 ? (
        <ProgressBar value={(step + 1) / STAGE_ORDER.length} label={statusLabel(t, material)} className="w-full" />
      ) : null}
    </span>
  );
}

export function dueText(t: TFunction, days: number): string {
  if (days < 0) return t("dashboard.overdue", { days: -days });
  if (days === 0) return t("dashboard.dueToday");
  if (days === 1) return t("dashboard.dueTomorrow");
  return t("dashboard.dueIn", { days });
}

export function dueTone(days: number): Tone {
  if (days < 0) return "danger";
  if (days <= 7) return "warning";
  return "neutral";
}
