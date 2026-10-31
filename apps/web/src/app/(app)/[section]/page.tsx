import Link from "next/link";
import { notFound } from "next/navigation";

import { EmptyState, PageHeader } from "@/components/page";
import { getT } from "@/i18n/server";
import { NAV_ITEMS } from "@/lib/nav";

export const dynamicParams = false;

// Only pages that are still placeholders live here; built pages have their own route.
const placeholders = NAV_ITEMS.filter((item) => !item.built);

export function generateStaticParams() {
  return placeholders.map((item) => ({ section: item.href.slice(1) }));
}

export default async function SectionPage({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  const item = placeholders.find((candidate) => candidate.href === `/${section}`);
  if (!item) notFound();
  const { t } = await getT();

  return (
    <>
      <PageHeader title={t(item.label)} description={t(item.description)} />
      <EmptyState
        title={t("section.plannedFor", { label: t(item.label), step: t("common.step", { n: item.step }) })}
        description={t("section.notBuilt")}
      >
        <Link
          href="/dashboard"
          className="rounded-xl border border-border px-4 py-2.5 text-sm font-medium hover:bg-bg"
        >
          {t("section.backToDashboard")}
        </Link>
      </EmptyState>
    </>
  );
}
