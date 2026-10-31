import { GuideView } from "@/components/guide-view";
import { PageHeader } from "@/components/page";
import { getT } from "@/i18n/server";
import { getGuide } from "@/lib/guide";

export const metadata = { title: "Help & Guide · MindNest AI" };

export default async function GuidePage() {
  const { t, locale } = await getT();
  const guide = getGuide(locale);
  return (
    <>
      <div id="top" />
      <PageHeader title={guide.title} description={t("navdesc.guide")} />
      <GuideView guide={guide} />
    </>
  );
}
