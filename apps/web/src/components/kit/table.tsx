import clsx from "clsx";
import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";

/** A dense data table: thin rules, small caps header, hover rows. Wrap it in a Panel or give it
 *  a border; it scrolls sideways inside its own box on a narrow screen. */
export function Table({ children, className, caption }: { children: ReactNode; className?: string; caption?: string }) {
  return (
    <div className={clsx("overflow-x-auto", className)}>
      <table className="w-full text-[13.5px]">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        {children}
      </table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return <thead className="border-b border-border">{children}</thead>;
}

export function TBody({ children }: { children: ReactNode }) {
  return <tbody className="divide-y divide-border">{children}</tbody>;
}

export function Tr({ className, ...rest }: HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={clsx("transition-colors hover:bg-surface-3/40", className)} {...rest} />;
}

export function Th({ className, align = "left", ...rest }: ThHTMLAttributes<HTMLTableCellElement> & { align?: "left" | "right" | "center" }) {
  return (
    <th
      scope="col"
      className={clsx(
        "whitespace-nowrap px-3 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-faint first:pl-4 last:pr-4 rtl:tracking-normal",
        align === "right" ? "text-right" : align === "center" ? "text-center" : "text-left",
        className,
      )}
      {...rest}
    />
  );
}

export function Td({ className, align = "left", ...rest }: TdHTMLAttributes<HTMLTableCellElement> & { align?: "left" | "right" | "center" }) {
  return (
    <td
      className={clsx(
        "px-3 py-3 align-middle first:pl-4 last:pr-4",
        align === "right" ? "text-right" : align === "center" ? "text-center" : "text-left",
        className,
      )}
      {...rest}
    />
  );
}
