import { ForgotPasswordForm } from "@/components/auth-forms";
import { getT } from "@/i18n/server";

export default async function ForgotPasswordPage() {
  const { t } = await getT();
  return (
    <>
      <h1 className="font-display text-2xl font-bold tracking-tight">{t("auth.forgotTitle")}</h1>
      <p className="mb-8 mt-1 text-muted">{t("auth.forgotSubtitle")}</p>
      <ForgotPasswordForm />
    </>
  );
}
