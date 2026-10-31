import clsx from "clsx";

import { Card } from "@/components/kit/card";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={clsx("skeleton", className)} />;
}

export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div aria-hidden className={clsx("space-y-2", className)}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={clsx("h-3.5", i === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}

export function SkeletonCard({ className, lines = 3 }: { className?: string; lines?: number }) {
  return (
    <Card className={clsx("p-5", className)} aria-hidden>
      <Skeleton className="h-8 w-8" />
      <Skeleton className="mt-4 h-4 w-1/2" />
      <SkeletonText lines={lines} className="mt-3" />
    </Card>
  );
}

/** What a page shows while its data loads: a title bar, a row of tiles and two panels. */
export function PageSkeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" aria-label={label}>
      <span className="sr-only">{label}</span>
      <Skeleton className="h-8 w-64" />
      <Skeleton className="mt-3 h-4 w-96 max-w-full" />
      <div className="mt-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <SkeletonCard key={i} lines={1} />
        ))}
      </div>
      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <SkeletonCard className="lg:col-span-2" lines={5} />
        <SkeletonCard lines={5} />
      </div>
    </div>
  );
}
