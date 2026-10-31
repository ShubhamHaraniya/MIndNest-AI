import { PageHeader } from "@/components/page";
import { PlannerView } from "@/components/planner-view";
import { getT } from "@/i18n/server";
import { serverFetch } from "@/lib/api-server";
import type { SubjectPage } from "@/lib/types";

export const metadata = { title: "Study Planner · MindNest AI" };

export default async function PlannerPage() {
  const { t } = await getT();
  const response = await serverFetch("/subjects?limit=100");
  const subjects = response.ok ? ((await response.json()) as SubjectPage).items : [];
  return (
    <>
      <PageHeader title={t("nav.planner")} description={t("navdesc.planner")} help="planner" />
      <PlannerView subjects={subjects} />
    </>
  );
}
