import { CalendarWorkspace } from "@/components/calendar/workspace";
import { PageHeader } from "@/components/page";
import { getT } from "@/i18n/server";
import { serverFetch } from "@/lib/api-server";
import type { SubjectPage } from "@/lib/types";

export const metadata = { title: "Calendar · MindNest AI" };

export default async function CalendarPage({
  searchParams,
}: {
  searchParams: Promise<{ gcal?: string | string[] }>;
}) {
  const { t } = await getT();
  const { gcal } = await searchParams;
  const response = await serverFetch("/subjects?limit=100");
  const subjects = response.ok ? ((await response.json()) as SubjectPage).items : [];
  return (
    <>
      <PageHeader title={t("nav.calendar")} description={t("navdesc.calendar")} help="calendar" />
      <CalendarWorkspace subjects={subjects} initialNotice={typeof gcal === "string" ? gcal : undefined} />
    </>
  );
}
