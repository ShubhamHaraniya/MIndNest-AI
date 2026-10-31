"use client";

import { Languages } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { api } from "@/lib/api";
import { LOCALES, LOCALE_COOKIE, LOCALE_NAMES, isLocale } from "@/i18n/config";
import { useLocale, useT } from "@/i18n/client";

export function setLocaleCookie(locale: string) {
  document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=31536000; samesite=lax`;
}

/** Changes the interface language. When `persist` is set the choice is also saved to the
 *  signed-in user's profile, so it follows them to other devices. */
export function LocaleSwitcher({ persist = false }: { persist?: boolean }) {
  const locale = useLocale();
  const t = useT();
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function change(value: string) {
    if (!isLocale(value)) return;
    setLocaleCookie(value);
    if (persist) void api("/me", { method: "PATCH", body: { ui_language: value } }).catch(() => {});
    startTransition(() => router.refresh());
  }

  return (
    <label className="inline-flex items-center gap-2 text-sm text-muted">
      <Languages className="h-4 w-4" aria-hidden />
      <span className="sr-only">{t("common.language")}</span>
      <select
        value={locale}
        disabled={pending}
        onChange={(event) => change(event.target.value)}
        className="rounded-lg border border-border bg-surface px-2 py-1.5 text-sm text-ink"
      >
        {LOCALES.map((code) => (
          <option key={code} value={code}>
            {LOCALE_NAMES[code]}
          </option>
        ))}
      </select>
    </label>
  );
}
