import { LibraryHub } from "@/components/library-hub";
import { PageHeader } from "@/components/page";
import { getT } from "@/i18n/server";

export const metadata = { title: "Study Groups · MindNest AI" };

export default async function LibraryPage() {
  const { t } = await getT();
  return (
    <>
      <PageHeader title={t("nav.library")} description={t("navdesc.library")} help="groups" />
      <LibraryHub />
    </>
  );
}
