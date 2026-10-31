"use client";

import clsx from "clsx";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "soft" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg" | "icon";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-primary text-on-primary shadow-card ring-1 ring-inset ring-white/20 hover:bg-primary-hover hover:shadow-glow",
  secondary:
    "border border-border-strong bg-surface-2/60 text-ink shadow-card backdrop-blur-sm hover:border-faint hover:bg-surface-3/80",
  soft: "bg-primary-soft text-brand hover:brightness-125",
  ghost: "text-muted hover:bg-surface-3/70 hover:text-ink",
  danger: "bg-danger text-on-primary hover:brightness-110",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 rounded-lg px-3 text-xs",
  md: "h-10 gap-2 rounded-control px-4 text-sm",
  lg: "h-11 gap-2 rounded-control px-6 text-[15px]",
  icon: "h-10 w-10 rounded-control",
};

export function buttonClass(variant: ButtonVariant = "primary", size: ButtonSize = "md", extra?: string): string {
  return clsx(
    "inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap font-semibold transition-colors active:translate-y-px",
    "disabled:pointer-events-none disabled:opacity-50",
    VARIANTS[variant],
    SIZES[size],
    extra,
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  className,
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClass(variant, size, className)}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
      {children}
    </button>
  );
}

type ButtonLinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: ReactNode;
};

/** A link that looks like a button, so navigation stays a real <a> (middle-click, new tab). */
export function ButtonLink({ href, variant = "primary", size = "md", className, children, ...rest }: ButtonLinkProps) {
  return (
    <Link href={href} className={buttonClass(variant, size, className)} {...rest}>
      {children}
    </Link>
  );
}
