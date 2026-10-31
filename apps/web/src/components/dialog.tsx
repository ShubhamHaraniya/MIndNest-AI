"use client";

import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

import { useT } from "@/i18n/client";

/** A modal built on the native <dialog> element, which gives focus trapping, Escape to close
 *  and an inert background without extra code. */
export function Dialog({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const t = useT();
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(event) => {
        // A click on the backdrop lands on the <dialog> element itself.
        if (event.target === ref.current) onClose();
      }}
      aria-labelledby={titleId}
      className={`m-auto max-h-[90vh] w-[calc(100%-2rem)] ${wide ? "max-w-3xl" : "max-w-lg"} animate-pop-in glass-dialog overflow-y-auto rounded-3xl p-0 text-ink`}
    >
      {open ? (
        <div className="p-6">
          <div className="mb-5 flex items-start justify-between gap-4">
            <h2 id={titleId} className="font-display text-lg font-semibold">
              {title}
            </h2>
            <button
              type="button"
              onClick={onClose}
              aria-label={t("common.close")}
              className="rounded-lg p-1.5 text-muted transition-colors hover:bg-surface-3 hover:text-ink"
            >
              <X className="h-5 w-5" aria-hidden />
            </button>
          </div>
          {children}
        </div>
      ) : null}
    </dialog>
  );
}
