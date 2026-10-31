import { ResetPasswordForm } from "@/components/auth-forms";
import { getT } from "@/i18n/server";

export default async function ResetPasswordPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  const { t } = await getT();
  return (
    <>
      <h1 className="mb-8 font-display text-2xl font-bold tracking-tight">{t("auth.resetTitle")}</h1>
      <ResetPasswordForm token={token ?? null} />
    </>
  );
}
