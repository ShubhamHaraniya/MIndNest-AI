"use client";

import { Panel } from "@/components/kit/panel";
import { useT } from "@/i18n/client";
import { METRIC_GROUPS } from "@/lib/eval";

/** Every score in plain words, so nobody has to guess what "MRR" or "Hit@K" measures. */
export function MetricGlossary({ only }: { only?: Set<string> }) {
  const t = useT();
  return (
    <Panel id="eval-glossary" title={t("evx.glossary.title")} description={t("evx.glossary.intro")} bodyClassName="px-3.5 py-3">
      <div className="space-y-4">
        {METRIC_GROUPS.map((group) => {
          const metrics = group.metrics.filter((m) => !only || only.has(m.key));
          if (metrics.length === 0) return null;
          return (
            <section key={group.title} aria-label={t(group.title)}>
              <h3 className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{t(group.title)}</h3>
              <dl className="mt-1 divide-y divide-border">
                {metrics.map((metric) => (
                  <div key={metric.key} className="grid gap-x-4 gap-y-0.5 py-2 sm:grid-cols-[14rem_1fr]">
                    <dt className="text-[13px] font-medium">
                      {t(metric.label)}
                      {metric.lowerIsBetter ? <span className="ml-2 text-xs font-normal text-muted">{t("eval.lowerIsBetter")}</span> : null}
                    </dt>
                    <dd className="text-[13px] text-muted">{t(metric.about)}</dd>
                  </div>
                ))}
              </dl>
            </section>
          );
        })}
      </div>
    </Panel>
  );
}
