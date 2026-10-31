import { MaterialsLibrary } from "@/components/library/materials-library";
import { PageHeader } from "@/components/page";
import { getT } from "@/i18n/server";
import { fetchMe } from "@/lib/api-server";
import { redirect } from "next/navigation";

export const metadata = { title: "Materials Library · MindNest AI" };

export default async function MaterialsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { t } = await getT();
  const user = await fetchMe();
  if (!user) redirect("/login?next=/materials");
  const params = await searchParams;
  const scope = typeof params.scope === "string" ? params.scope : undefined;
  return (
    <>
      <PageHeader title={t("nav.materials")} description={t("navdesc.materials")} help="library" />
      <MaterialsLibrary user={user} initialScope={scope} />
    </>
  );
}
