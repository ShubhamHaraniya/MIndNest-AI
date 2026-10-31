import { notFound } from "next/navigation";

import { AdminView } from "@/components/admin-view";
import { PageHeader } from "@/components/page";
import { getT } from "@/i18n/server";
import { fetchMe } from "@/lib/api-server";

export const metadata = { title: "Admin · MindNest AI" };

export default async function AdminPage() {
  const me = await fetchMe();
  // The API checks again on every request; this just keeps the page from showing to everyone else.
  if (!me?.is_admin) notFound();
  const { t } = await getT();
  return (
    <>
      <PageHeader title={t("nav.admin")} description={t("navdesc.admin")} />
      <AdminView />
    </>
  );
}
