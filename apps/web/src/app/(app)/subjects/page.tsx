import { cookies } from "next/headers";

import { COURSE_COOKIE } from "@/components/shell/course";
import { SubjectsView } from "@/components/subjects-view";
import { PageHeader } from "@/components/page";
import { getT } from "@/i18n/server";

export const metadata = { title: "My Subjects · MindNest AI" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function SubjectsPage({
  searchParams,
}: {
  searchParams: Promise<{ new?: string }>;
}) {
  const { t } = await getT();
  const openNew = (await searchParams).new === "1";
  const chosen = (await cookies()).get(COURSE_COOKIE)?.value ?? null;
  return (
    <>
      <PageHeader title={t("subjects.title")} description={t("subjects.subtitle")} help="subjects" />
      <SubjectsView openNewOnLoad={openNew} currentId={chosen && UUID.test(chosen) ? chosen : null} />
    </>
  );
}
