"use client";

import { useEffect } from "react";

import { ButtonLink } from "@/components/kit/button";
import { ErrorState } from "@/components/kit/states";
import { useT } from "@/i18n/client";

/** Any page that throws while rendering lands here instead of a blank screen. */
export default function AppError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const t = useT();
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <ErrorState onRetry={reset}>
      <ButtonLink href="/dashboard" variant="secondary">
        {t("state.backToDashboard")}
      </ButtonLink>
    </ErrorState>
  );
}
