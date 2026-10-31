"use client";

import clsx from "clsx";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import { useT } from "@/i18n/client";

type ToastTone = "success" | "error" | "info";
type ToastItem = { id: number; tone: ToastTone; message: string };

type ToastApi = {
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

const ICONS = { success: CheckCircle2, error: AlertCircle, info: Info };
const TONES = {
  success: "text-success",
  error: "text-danger",
  info: "text-info",
};
const LIFETIME_MS = 5000;

/** Short confirmations ("Saved", "Quiz created") in the corner. Announced politely to screen
 *  readers, and they dismiss themselves. Errors that need a decision belong in the page instead. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const next = useRef(1);
  const t = useT();

  const dismiss = useCallback((id: number) => setItems((all) => all.filter((item) => item.id !== id)), []);
  const push = useCallback(
    (tone: ToastTone, message: string) => {
      const id = next.current++;
      setItems((all) => [...all.slice(-3), { id, tone, message }]);
      window.setTimeout(() => dismiss(id), LIFETIME_MS);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (message) => push("success", message),
      error: (message) => push("error", message),
      info: (message) => push("info", message),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 sm:items-end sm:p-6"
      >
        {items.map((item) => {
          const Icon = ICONS[item.tone];
          return (
            <div
              key={item.id}
              role={item.tone === "error" ? "alert" : "status"}
              className="pointer-events-auto flex w-full max-w-sm animate-toast-in items-start gap-3 glass-strong rounded-2xl p-3.5"
            >
              <Icon className={clsx("mt-0.5 h-5 w-5 shrink-0", TONES[item.tone])} aria-hidden />
              <p className="min-w-0 flex-1 text-sm">{item.message}</p>
              <button
                type="button"
                onClick={() => dismiss(item.id)}
                aria-label={t("common.close")}
                className="rounded-md p-0.5 text-muted hover:text-ink"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside <ToastProvider>.");
  return value;
}
