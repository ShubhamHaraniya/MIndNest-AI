import { redirect } from "next/navigation";

import { LoginForm } from "@/components/auth-forms";
import { GoogleSignIn } from "@/components/google-button";
import { Alert } from "@/components/ui";
import { getT } from "@/i18n/server";
import { fetchMe, fetchProviders } from "@/lib/api-server";
import { safeNext } from "@/lib/utils";

const GOOGLE_PROBLEMS = {
  google_failed: "auth.google.error.failed",
  google_cancelled: "auth.google.error.cancelled",
  google_unverified: "auth.google.error.unverified",
  google_disabled: "auth.google.error.disabled",
  google_not_configured: "auth.google.error.notConfigured",
} as const;

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const query = await searchParams;
  const next = safeNext(query.next);
  const user = await fetchMe();
  if (user) redirect(user.onboarding_completed ? next : "/onboarding");
  const { t } = await getT();
  const { google } = await fetchProviders();
  const problem = GOOGLE_PROBLEMS[(query.error ?? "") as keyof typeof GOOGLE_PROBLEMS];
  return (
    <>
      <h1 className="font-display text-2xl font-bold tracking-tight">{t("auth.loginTitle")}</h1>
      <p className="mb-8 mt-1 text-muted">{t("auth.loginSubtitle")}</p>
      {problem ? (
        <div className="mb-5">
          <Alert>{t(problem)}</Alert>
        </div>
      ) : null}
      {google ? <GoogleSignIn next={next} /> : null}
      <LoginForm next={next} />
    </>
  );
}
