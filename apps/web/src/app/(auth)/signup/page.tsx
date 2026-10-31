import { redirect } from "next/navigation";

import { SignupForm } from "@/components/auth-forms";
import { GoogleSignIn } from "@/components/google-button";
import { getT } from "@/i18n/server";
import { fetchMe, fetchProviders } from "@/lib/api-server";

export default async function SignupPage() {
  const user = await fetchMe();
  if (user) redirect(user.onboarding_completed ? "/dashboard" : "/onboarding");
  const { t } = await getT();
  const { google } = await fetchProviders();
  return (
    <>
      <h1 className="font-display text-2xl font-bold tracking-tight">{t("auth.signupTitle")}</h1>
      <p className="mb-8 mt-1 text-muted">{t("auth.signupSubtitle")}</p>
      {google ? <GoogleSignIn /> : null}
      <SignupForm />
    </>
  );
}
