import Link from "next/link";

/** The MindNest mark: a rounded emerald-to-cyan tile with a bold "M". Drawn inline so it follows the theme and
 *  needs no image file. */
export function BrandMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={`font-display flex items-center justify-center rounded-xl bg-gradient-to-br from-primary to-accent text-[15px] font-bold leading-none text-on-primary shadow-glow ring-1 ring-inset ring-white/30 ${className}`}
    >
      M
    </span>
  );
}

export function Brand({ href = "/", className = "", compact = false }: { href?: string; className?: string; compact?: boolean }) {
  return (
    <Link href={href} className={`flex items-center gap-2 ${className}`} aria-label="MindNest AI">
      <BrandMark />
      {compact ? null : (
        <span className="font-display text-[18px] leading-none">
          MindNest <span className="text-faint">AI</span>
        </span>
      )}
    </Link>
  );
}
