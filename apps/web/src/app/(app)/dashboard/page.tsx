import { cookies } from "next/headers";

import { Workbench } from "@/components/dashboard/workbench";
import { ButtonLink } from "@/components/kit/button";
import { ErrorState } from "@/components/kit/states";
import { COURSE_COOKIE } from "@/components/shell/course";
import { getT } from "@/i18n/server";
import { fetchMe, serverFetch } from "@/lib/api-server";
import type { DashboardData } from "@/lib/types";

export const metadata = { title: "Dashboard · MindNest AI" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function DashboardPage() {
  const { t, locale } = await getT();
  const chosen = (await cookies()).get(COURSE_COOKIE)?.value;
  const query = chosen && UUID.test(chosen) ? `?course=${chosen}` : "";
  const [user, response] = await Promise.all([fetchMe(), serverFetch(`/dashboard${query}`)]);

  if (!response.ok) {
    return (
      <ErrorState>
        <ButtonLink href="/dashboard">{t("common.retry")}</ButtonLink>
      </ErrorState>
    );
  }
  const data = (await response.json()) as DashboardData;
  const name = (user?.display_name ?? "").trim().split(/\s+/)[0] ?? "";
  return <Workbench data={data} name={name} t={t} locale={locale} />;
}
