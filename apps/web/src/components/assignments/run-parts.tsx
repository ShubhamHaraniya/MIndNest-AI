"use client";

import clsx from "clsx";
import { Check, ExternalLink, Loader2, RotateCw } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/kit/button";
import { Select } from "@/components/kit/controls";
import { useT } from "@/i18n/client";
import { failureText, isWorking } from "@/lib/assignments";
import type { AssignmentRun, Language, RunSource } from "@/lib/types";

const LANGUAGES: Language[] = ["en", "hi", "gu"];

export function LanguagePicker({ value, onChange }: { value: Language; onChange: (value: Language) => void }) {
  const t = useT();
  return (
    <label className="flex shrink-0 items-center gap-1.5 text-xs text-muted">
      <span>{t("assign.detail.language")}</span>
      <Select
        value={value}
        onChange={(event) => onChange(event.target.value as Language)}
        className="h-7 px-2 text-xs"
      >
        {LANGUAGES.map((code) => (
          <option key={code} value={code}>
            {t(`eval.lang.${code}`)}
          </option>
        ))}
      </Select>
    </label>
  );
}

/** A small uppercase label with optional controls on the right: one block of the context pane. */
export function Block({
  title,
  action,
  children,
  className,
}: {
  title: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={clsx("px-3.5 py-3", className)}>
      <div className="mb-2 flex min-h-7 items-center justify-between gap-2">
        <h3 className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{title}</h3>
        {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
      </div>
      {children}
    </section>
  );
}

/** The button that asks for help (or asks again) and its state. */
export function RunButton({
  run,
  starting,
  blocked,
  onAsk,
  label,
  primary = false,
}: {
  run: AssignmentRun | undefined;
  starting: boolean;
  blocked: string | null;
  onAsk: () => void;
  label: string;
  primary?: boolean;
}) {
  const t = useT();
  const working = run ? isWorking(run.status) : false;
  const again = run?.status === "ready" || run?.status === "failed";
  return (
    <Button
      size="sm"
      variant={again || !primary ? "secondary" : "primary"}
      loading={starting || working}
      disabled={blocked !== null}
      title={blocked ?? undefined}
      onClick={onAsk}
    >
      {again ? <RotateCw className="h-3.5 w-3.5" aria-hidden /> : null}
      {again ? t("assign.detail.rerun") : label}
    </Button>
  );
}

/** What to show in place of a result while there is none: working, failed, or nothing yet. */
export function RunState({ run, idle }: { run: AssignmentRun | undefined; idle: ReactNode }) {
  const t = useT();
  if (run && isWorking(run.status)) {
    return (
      <p role="status" className="flex items-center gap-2 text-[13px] text-muted">
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
        {t("assign.detail.working")}
      </p>
    );
  }
  if (run?.status === "failed") {
    return (
      <p role="alert" className="rounded-xl border border-danger/30 bg-danger-soft px-2.5 py-2 text-[13px] text-danger">
        {failureText(run.error, t)}
      </p>
    );
  }
  return <>{idle}</>;
}

/** The passages of the student's own files an answer relied on, each opening the file. */
export function SourceList({ sources, picked }: { sources: RunSource[]; picked?: number | null }) {
  const t = useT();
  if (sources.length === 0) return <p className="text-xs text-muted">{t("assign.detail.noSources")}</p>;
  return (
    <ol className="space-y-0.5 text-xs">
      {sources.map((source) => (
        <li key={source.n}>
          <a
            href={`/api/v1/materials/${source.material_id}/download?inline=true${source.page ? `#page=${source.page}` : ""}`}
            target="_blank"
            rel="noopener noreferrer"
            className={clsx(
              "flex items-baseline gap-2 rounded px-1.5 py-1 hover:bg-surface-2",
              picked === source.n && "bg-primary-soft",
            )}
          >
            <span className="w-5 shrink-0 font-semibold text-brand">[{source.n}]</span>
            <span className="min-w-0 flex-1 truncate">{source.filename}</span>
            {source.page !== null ? (
              <span className="shrink-0 text-muted">{t("assign.detail.page", { n: source.page })}</span>
            ) : null}
            <ExternalLink className="h-3 w-3 shrink-0 text-faint" aria-hidden />
          </a>
        </li>
      ))}
    </ol>
  );
}

/** Items to tick off. Ticks are kept in this browser (per assignment), not on the server: they
 *  are a reading aid, not part of the assignment. */
export function Checklist({ items, storageKey, label }: { items: string[]; storageKey: string; label: string }) {
  const t = useT();
  const [done, setDone] = useState<Set<string>>(new Set());

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(storageKey);
      setDone(new Set(stored ? (JSON.parse(stored) as string[]) : []));
    } catch {
      setDone(new Set());
    }
  }, [storageKey]);

  function toggle(item: string) {
    setDone((current) => {
      const next = new Set(current);
      if (next.has(item)) next.delete(item);
      else next.add(item);
      try {
        window.localStorage.setItem(storageKey, JSON.stringify([...next]));
      } catch {
        // Private windows can refuse storage; the ticks then last until the page closes.
      }
      return next;
    });
  }

  const count = items.filter((item) => done.has(item)).length;
  return (
    <div>
      <ul aria-label={label} className="divide-y divide-border rounded-xl border border-border">
        {items.map((item) => {
          const checked = done.has(item);
          return (
            <li key={item}>
              <button
                type="button"
                role="checkbox"
                aria-checked={checked}
                onClick={() => toggle(item)}
                className="flex w-full items-start gap-2.5 px-2.5 py-2 text-left hover:bg-surface-2"
              >
                <span
                  aria-hidden
                  className={clsx(
                    "mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-md border",
                    checked ? "border-primary bg-primary text-on-primary" : "border-border-strong bg-surface",
                  )}
                >
                  {checked ? <Check className="h-3 w-3" /> : null}
                </span>
                <span className={clsx("min-w-0 flex-1 text-[13px] leading-5", checked && "text-faint line-through")}>
                  <InlineText text={item} />
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="tabular mt-1.5 text-xs text-muted">{t("asw.check.progress", { done: count, total: items.length })}</p>
    </div>
  );
}

/** **bold** and `code` in a single line of text, nothing else. */
export function InlineText({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((part, index) =>
        part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
          <strong key={index} className="font-semibold">
            {part.slice(2, -2)}
          </strong>
        ) : part.startsWith("`") && part.endsWith("`") && part.length > 2 ? (
          <code key={index} className="rounded-sm bg-surface-3 px-1 font-mono text-[12px]">
            {part.slice(1, -1)}
          </code>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}
