import { EvalLab } from "@/components/eval-lab";
import { PageHeader } from "@/components/page";
import { getT } from "@/i18n/server";
import { serverFetch } from "@/lib/api-server";
import type { SubjectPage } from "@/lib/types";

export default async function EvalPage({ searchParams }: { searchParams: Promise<{ run?: string }> }) {
  const { t } = await getT();
  const { run } = await searchParams;
  const response = await serverFetch("/subjects?limit=100");
  const subjects = response.ok ? ((await response.json()) as SubjectPage).items : [];

  return (
    <>
      <PageHeader title={t("nav.eval")} description={t("navdesc.eval")} help="eval" />
      <EvalLab subjects={subjects} openRunFor={run ?? null} />
    </>
  );
}
