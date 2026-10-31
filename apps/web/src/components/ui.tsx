"use client";

import clsx from "clsx";
import { AlertCircle, CheckCircle2, Eye, EyeOff, Info } from "lucide-react";
import { forwardRef, useId, useState, type InputHTMLAttributes, type ReactNode } from "react";

import { useT } from "@/i18n/client";

// Button now lives in the design kit; it is re-exported here so existing imports keep working.
export { Button } from "@/components/kit/button";

type FieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  hint?: string;
  error?: string | null;
  optionalLabel?: string;
};

export const Field = forwardRef<HTMLInputElement, FieldProps>(function Field(
  { label, hint, error, optionalLabel, className, id, type, ...rest },
  ref,
) {
  const generated = useId();
  const inputId = id ?? generated;
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;
  const [revealed, setRevealed] = useState(false);
  const t = useT();
  const isPassword = type === "password";

  return (
    <div className={className}>
      <label htmlFor={inputId} className="mb-1 block text-[13px] font-medium">
        {label}
        {optionalLabel ? <span className="ml-1 font-normal text-muted">({optionalLabel})</span> : null}
      </label>
      <div className="relative">
        <input
          ref={ref}
          id={inputId}
          type={isPassword && revealed ? "text" : type}
          aria-invalid={error ? true : undefined}
          aria-describedby={clsx(hint && hintId, error && errorId) || undefined}
          className={clsx(
            "h-10 w-full rounded-control border bg-surface-2/60 px-3.5 text-sm text-ink placeholder:text-faint",
            "hover:border-border-strong focus:border-primary focus:outline-none",
            error ? "border-danger" : "border-border-strong",
            isPassword && "pr-10",
          )}
          {...rest}
        />
        {isPassword ? (
          <button
            type="button"
            onClick={() => setRevealed((value) => !value)}
            aria-label={revealed ? t("auth.hidePassword") : t("auth.showPassword")}
            className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-muted hover:text-ink"
          >
            {revealed ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
          </button>
        ) : null}
      </div>
      {hint && !error ? (
        <p id={hintId} className="mt-1.5 text-xs text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="mt-1.5 text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
});

export function Alert({
  tone = "error",
  children,
}: {
  tone?: "error" | "success" | "info";
  children: ReactNode;
}) {
  const styles = {
    error: "border-danger/30 bg-danger-soft text-danger",
    success: "border-success/30 bg-success-soft text-success",
    info: "border-border bg-primary-soft text-ink",
  }[tone];
  const Icon = tone === "error" ? AlertCircle : tone === "success" ? CheckCircle2 : Info;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={clsx("flex items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-[13px]", styles)}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
