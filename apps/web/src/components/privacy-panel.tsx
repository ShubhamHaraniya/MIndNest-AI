"use client";

import { ShieldCheck } from "lucide-react";
import { useState } from "react";

import { Alert } from "@/components/ui";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { User } from "@/lib/types";

export function PrivacyPanel({ initialMask }: { initialMask: boolean }) {
  const t = useT();
  const [mask, setMask] = useState(initialMask);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function change(next: boolean) {
    const previous = mask;
    setMask(next);
    setSaving(true);
    setError(null);
    try {
      const saved = await api<User>("/me", { method: "PATCH", body: { mask_personal_data: next } });
      setMask(saved.mask_personal_data);
    } catch (caught) {
      setMask(previous);
      setError(errorMessage(caught, t));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-labelledby="privacy-title" className="rounded-card border border-border bg-surface p-5">
      <h2 id="privacy-title" className="flex items-center gap-2 text-lg font-semibold">
        <ShieldCheck className="h-5 w-5 text-primary" aria-hidden />
        {t("privacy.title")}
      </h2>
      <p className="mt-1 max-w-2xl text-sm text-muted">{t("privacy.intro")}</p>
      <ul className="mt-3 max-w-2xl list-disc space-y-1 pl-5 text-sm text-muted">
        <li>{t("privacy.always")}</li>
        <li>{t("privacy.injection")}</li>
        <li>{t("privacy.output")}</li>
      </ul>
      <label className="mt-4 flex max-w-2xl items-start gap-3 text-sm">
        <input
          type="checkbox"
          checked={mask}
          disabled={saving}
          onChange={(event) => void change(event.target.checked)}
          className="mt-0.5"
        />
        <span>
          <span className="font-medium">{t("privacy.toggle")}</span>
          <span className="mt-0.5 block text-muted">{t("privacy.toggleHint")}</span>
        </span>
      </label>
      {error ? (
        <div className="mt-3">
          <Alert>{error}</Alert>
        </div>
      ) : null}
    </section>
  );
}
