"use client";

import { motion } from "motion/react";

import { useT } from "@/i18n/client";
import { percent } from "@/lib/format";

import { NO_MODULE, type ModuleProgress } from "./model";

/** The syllabus as one ribbon: a segment per module, as wide as the files it holds, filled to the
 *  student's accuracy on it. Each segment opens that module's files. */
export function SyllabusRibbon({ modules, onOpen }: { modules: ModuleProgress[]; onOpen: (module: string) => void }) {
  const t = useT();
  const named = modules.filter((m) => m.module !== null);
  const rows = named.length > 0 ? named : modules;
  const practised = rows.filter((m) => m.answers > 0).length;
  if (rows.length === 0) return null;

  return (
    <div className="border-b border-border px-4 pb-4 pt-3.5">
      <div className="mb-2 flex items-baseline justify-between gap-3 text-xs text-muted">
        <span>{t("sj.col.practised")}</span>
        <span className="tabular font-semibold text-ink">
          {practised} / {rows.length}
        </span>
      </div>
      <ul className="flex gap-1.5">
        {rows.map((row, index) => {
          const label = row.module ?? t("sj.module.none");
          const fill = row.accuracy ?? 0;
          const tone = row.weak ? "from-danger to-warning" : row.accuracy !== null && row.accuracy >= 0.8 ? "from-primary to-accent" : "from-warning to-primary";
          return (
            <li key={row.module ?? NO_MODULE} style={{ flexGrow: Math.max(row.documents, 1), flexBasis: 0 }} className="min-w-[2.5rem]">
              <button
                type="button"
                onClick={() => onOpen(row.module ?? NO_MODULE)}
                title={`${label}: ${percent(row.accuracy)}`}
                aria-label={`${label}: ${t("sj.progress.accuracyOf", { name: label })} ${percent(row.accuracy)}`}
                className="group block w-full text-left"
              >
                <span className="block h-3 overflow-hidden rounded-full bg-surface-3 ring-1 ring-inset ring-border">
                  <motion.span
                    className={`block h-full rounded-full bg-gradient-to-r ${tone}`}
                    initial={{ width: 0 }}
                    whileInView={{ width: `${fill * 100}%` }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.9, delay: index * 0.07, ease: [0.22, 1, 0.36, 1] }}
                  />
                </span>
                <span className="mt-1.5 block truncate text-[11px] text-muted group-hover:text-brand">{label}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
