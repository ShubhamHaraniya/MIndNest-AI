"use client";

import { useLocale, useT } from "@/i18n/client";

/** The multi-colour Google "G". Inline so it needs no image request and follows no theme. */
function GoogleG() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden>
      <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.7v3h3.9c2.3-2.1 3.5-5.2 3.5-8.9z" />
      <path fill="#34A853" d="M12 24c3.2 0 6-1.1 7.9-2.9l-3.9-3c-1.1.7-2.5 1.2-4 1.2-3.1 0-5.7-2.1-6.6-4.9H1.4v3.1A12 12 0 0 0 12 24z" />
      <path fill="#FBBC05" d="M5.4 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.4a12 12 0 0 0 0 10.8l4-3.1z" />
      <path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.4 6.6l4 3.1C6.3 6.9 8.9 4.8 12 4.8z" />
    </svg>
  );
}

/** "Continue with Google". A plain link, because the browser must leave the app and come back. */
export function GoogleSignIn({ next = "/dashboard" }: { next?: string }) {
  const t = useT();
  const locale = useLocale();
  const href = `/api/v1/auth/google/start?lang=${locale}&next=${encodeURIComponent(next)}`;
  return (
    <div className="mb-6">
      <a
        href={href}
        className="flex h-11 w-full items-center justify-center gap-3 rounded-control border border-border-strong bg-surface-2/60 text-sm font-medium text-ink shadow-card transition-colors hover:border-faint hover:bg-surface-3/80"
      >
        <GoogleG />
        {t("auth.google.button")}
      </a>
      <div className="mt-5 flex items-center gap-3 text-xs uppercase tracking-wide text-faint" aria-hidden>
        <span className="h-px flex-1 bg-border" />
        {t("auth.or")}
        <span className="h-px flex-1 bg-border" />
      </div>
    </div>
  );
}
