import clsx from "clsx";

import { initials } from "@/lib/utils";

const SIZES = { sm: "h-7 w-7 text-[11px]", md: "h-9 w-9 text-xs", lg: "h-12 w-12 text-base" };

export function Avatar({ name, size = "md", className }: { name: string; size?: keyof typeof SIZES; className?: string }) {
  return (
    <span
      aria-hidden
      className={clsx(
        "flex shrink-0 items-center justify-center rounded-full bg-primary font-semibold text-on-primary",
        SIZES[size],
        className,
      )}
    >
      {initials(name)}
    </span>
  );
}
