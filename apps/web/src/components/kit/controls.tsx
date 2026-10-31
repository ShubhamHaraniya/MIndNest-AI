"use client";

import clsx from "clsx";
import { Search, X } from "lucide-react";
import type { ComponentPropsWithRef, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

import { useT } from "@/i18n/client";

/** Class strings for the plain form controls, so every page's inputs look the same. */
export const inputClass =
  "h-10 w-full rounded-control border border-border-strong bg-surface-2/60 px-3.5 text-sm text-ink placeholder:text-faint hover:border-faint focus:border-primary focus:ring-4 focus:ring-primary/15 focus:outline-none disabled:opacity-60";
export const selectClass =
  "h-10 rounded-control border border-border-strong bg-surface-2/60 px-3 text-sm text-ink hover:border-faint focus:border-primary focus:ring-4 focus:ring-primary/15 focus:outline-none disabled:opacity-60";
export const textareaClass =
  "w-full rounded-control border border-border-strong bg-surface-2/60 px-3.5 py-2.5 text-sm leading-relaxed text-ink placeholder:text-faint hover:border-faint focus:border-primary focus:ring-4 focus:ring-primary/15 focus:outline-none disabled:opacity-60";

export function Input({ className, ...rest }: ComponentPropsWithRef<"input">) {
  return <input className={clsx(inputClass, className)} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={clsx(selectClass, className)} {...rest}>
      {children}
    </select>
  );
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={clsx(textareaClass, className)} {...rest} />;
}

/** A labelled control: label above, optional hint below, error in red. */
export function FormRow({
  label,
  htmlFor,
  hint,
  error,
  children,
  className,
}: {
  label: ReactNode;
  htmlFor?: string;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label htmlFor={htmlFor} className="mb-1.5 block text-[13px] font-semibold">
        {label}
      </label>
      {children}
      {error ? <p className="mt-1 text-xs text-danger">{error}</p> : hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

/** A search box with a clear button; `value` is controlled by the page. */
export function SearchField({
  value,
  onChange,
  placeholder,
  label,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  label?: string;
  className?: string;
}) {
  const t = useT();
  return (
    <label className={clsx("relative block", className)}>
      <span className="sr-only">{label ?? placeholder}</span>
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" aria-hidden />
      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className={clsx(inputClass, "pl-8 pr-8 [&::-webkit-search-cancel-button]:hidden")}
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label={t("common.clear")}
          className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-muted hover:bg-surface-3 hover:text-ink"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      ) : null}
    </label>
  );
}

/** A compact either/or (or one-of-few) switch, used for filters and view modes. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  className,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: ReactNode; count?: number }[];
  label: string;
  className?: string;
}) {
  return (
    <div role="group" aria-label={label} className={clsx("inline-flex rounded-xl border border-border bg-surface-3/50 p-1", className)}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={clsx(
            "h-7 rounded-lg px-3 text-xs font-semibold transition-colors",
            value === option.value ? "bg-primary-soft text-brand shadow-card ring-1 ring-primary/30" : "text-muted hover:text-ink",
          )}
        >
          {option.label}
          {option.count !== undefined ? <span className="tabular ml-1 text-faint">{option.count}</span> : null}
        </button>
      ))}
    </div>
  );
}
