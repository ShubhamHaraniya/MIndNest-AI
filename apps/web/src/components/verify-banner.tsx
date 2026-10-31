"use client";

import { useState } from "react";

import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";

export function VerifyBanner({ email }: { email: string }) {
  const t = useT();
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  async function resend() {
    setState("sending");
    setError(null);
    try {
      await api("/auth/resend-verification", { method: "POST" });
      setState("sent");
    } catch (caught) {
      setError(errorMessage(caught, t));
      setState("idle");
    }
  }

  return (
    <div role="status" className="border-b border-warning/30 bg-warning/10 px-4 py-2.5 text-sm sm:px-8">
      <span>{t("auth.bannerText", { email })}</span>{" "}
      {state === "sent" ? (
        <span className="font-medium">{t("auth.bannerSent")}</span>
      ) : (
        <button
          type="button"
          onClick={() => void resend()}
          disabled={state === "sending"}
          className="font-medium text-primary underline disabled:opacity-60"
        >
          {t("auth.bannerResend")}
        </button>
      )}
      {error ? <span className="ml-2 text-danger">{error}</span> : null}
    </div>
  );
}
