import { ButtonLink } from "@/components/kit/button";
import { NoResults } from "@/components/kit/states";
import { getT } from "@/i18n/server";

export default async function AppNotFound() {
  const { t } = await getT();
  return (
    <NoResults title={t("state.notFoundTitle")} description={t("state.notFoundBody")}>
      <ButtonLink href="/dashboard">{t("state.backToDashboard")}</ButtonLink>
    </NoResults>
  );
}
