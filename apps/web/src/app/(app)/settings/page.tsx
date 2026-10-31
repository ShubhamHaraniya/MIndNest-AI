import { PageHeader } from "@/components/page";
import { SettingsView } from "@/components/settings-view";
import { getT } from "@/i18n/server";
import { fetchMe } from "@/lib/api-server";
import { redirect } from "next/navigation";

export const metadata = { title: "Settings · MindNest AI" };

export default async function SettingsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { t } = await getT();
  const user = await fetchMe();
  if (!user) redirect("/login?next=/settings");
  const params = await searchParams;
  const tab = typeof params.tab === "string" ? params.tab : undefined;
  const gcal = typeof params.gcal === "string" ? params.gcal : undefined;
  return (
    <>
      <PageHeader title={t("nav.settings")} description={t("navdesc.settings")} help="settings" />
      <SettingsView user={user} initialTab={gcal ? "calendar" : tab} gcalNotice={gcal} />
    </>
  );
}
