import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { Fragment } from "react";

export type Crumb = { label: string; href?: string };

/** Where you are: parent pages as links, the current page last. Long names are cut, not wrapped. */
export function Breadcrumbs({ items, label }: { items: Crumb[]; label: string }) {
  return (
    <nav aria-label={label} className="mb-2">
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-[13px] text-muted">
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <Fragment key={`${index}-${item.label}`}>
              <li className="min-w-0">
                {item.href && !last ? (
                  <Link href={item.href} className="hover:text-ink hover:underline">
                    {item.label}
                  </Link>
                ) : (
                  <span aria-current={last ? "page" : undefined} className="block max-w-[28ch] truncate text-ink sm:max-w-[48ch]" title={item.label}>
                    {item.label}
                  </span>
                )}
              </li>
              {last ? null : (
                <li aria-hidden className="text-faint">
                  <ChevronRight className="h-3.5 w-3.5 rtl:rotate-180" />
                </li>
              )}
            </Fragment>
          );
        })}
      </ol>
    </nav>
  );
}
