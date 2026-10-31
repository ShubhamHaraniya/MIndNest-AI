import { PageSkeleton } from "@/components/kit/skeleton";
import { getT } from "@/i18n/server";

export default async function Loading() {
  const { t } = await getT();
  return <PageSkeleton label={t("state.loadingPage")} />;
}
