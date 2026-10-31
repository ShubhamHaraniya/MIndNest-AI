"use client";

import { AlertTriangle } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Dialog } from "@/components/dialog";
import { Button } from "@/components/kit/button";
import { useT } from "@/i18n/client";

/** "Are you sure?" for anything that deletes, sends or cannot be undone. The confirm button names
 *  the action ("Delete subject"), never just "OK". */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  tone = "danger",
  onConfirm,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel: string;
  tone?: "danger" | "primary";
  onConfirm: () => void | Promise<void>;
  onClose: () => void;
  children?: ReactNode;
}) {
  const t = useT();
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    try {
      await onConfirm();
      onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={busy ? () => {} : onClose} title={title}>
      <div className="flex gap-3">
        {tone === "danger" ? (
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-danger-soft text-danger">
            <AlertTriangle className="h-5 w-5" aria-hidden />
          </span>
        ) : null}
        <div className="min-w-0 text-sm text-muted">
          {description ? <p>{description}</p> : null}
          {children}
        </div>
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          {t("common.cancel")}
        </Button>
        <Button variant={tone === "danger" ? "danger" : "primary"} loading={busy} onClick={() => void confirm()}>
          {confirmLabel}
        </Button>
      </div>
    </Dialog>
  );
}
