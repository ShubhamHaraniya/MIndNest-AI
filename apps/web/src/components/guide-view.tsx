"use client";

import { Lightbulb } from "lucide-react";
import { useMemo, useState } from "react";

import { SearchField } from "@/components/kit/controls";
import { NoResults } from "@/components/kit/states";
import { useT } from "@/i18n/client";
import type { Guide } from "@/lib/guide";

/** The student guide. It is plain text that reads and prints well; the search box narrows it to the
 *  parts that mention what you typed. */
export function GuideView({ guide }: { guide: Guide }) {
  const t = useT();
  const [query, setQuery] = useState("");

  const sections = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return guide.sections;
    return guide.sections.filter((section) =>
      [section.title, ...section.body, ...(section.steps ?? []), section.tip ?? ""].join(" ").toLocaleLowerCase().includes(needle),
    );
  }, [guide.sections, query]);

  return (
    <div className="grid gap-8 lg:grid-cols-[14rem_minmax(0,1fr)]">
      <nav aria-label={guide.contents} className="lg:sticky lg:top-6 lg:self-start print:hidden">
        <SearchField value={query} onChange={setQuery} placeholder={t("gx.search")} className="mb-3" />
        <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{guide.contents}</p>
        <ol className="space-y-0.5 text-[13px]">
          {sections.map((section) => (
            <li key={section.id}>
              <a href={`#${section.id}`} className="block rounded px-2 py-1.5 text-muted hover:bg-surface-3 hover:text-ink">
                {section.title}
              </a>
            </li>
          ))}
        </ol>
      </nav>

      <div className="max-w-3xl space-y-4">
        {query.trim() === "" ? <p className="text-base leading-relaxed">{guide.intro}</p> : (
          <p role="status" className="text-[13px] text-muted">
            {t("gx.found", { count: sections.length })}
          </p>
        )}
        {sections.length === 0 ? <NoResults title={t("gx.none")} description={t("gx.noneBody")} /> : null}
        {sections.map((section) => (
          <section key={section.id} id={section.id} className="scroll-mt-6 rounded-card border border-border bg-surface p-5">
            <h2 className="text-lg font-semibold">{section.title}</h2>
            <div className="mt-3 space-y-3 leading-relaxed">
              {section.body.map((paragraph, index) => (
                <p key={index}>{paragraph}</p>
              ))}
            </div>
            {section.steps && section.steps.length > 0 ? (
              <div className="mt-4">
                <p className="text-sm font-semibold text-muted">{guide.stepsLabel}</p>
                <ol className="mt-2 list-decimal space-y-1.5 pl-5 leading-relaxed marker:text-muted">
                  {section.steps.map((step, index) => (
                    <li key={index}>{step}</li>
                  ))}
                </ol>
              </div>
            ) : null}
            {section.tip ? (
              <p className="mt-4 flex gap-2 rounded bg-primary-soft p-3 text-sm leading-relaxed">
                <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
                <span>
                  <span className="font-semibold">{guide.tipLabel}: </span>
                  {section.tip}
                </span>
              </p>
            ) : null}
            <p className="mt-4 text-right text-xs print:hidden">
              <a href="#top" className="text-muted hover:text-ink">
                {guide.topLabel}
              </a>
            </p>
          </section>
        ))}
      </div>
    </div>
  );
}
