"use client";

import clsx from "clsx";
import { FileText, ImageIcon, Loader2 } from "lucide-react";

import { Meter } from "@/components/dashboard/meter";
import { Badge } from "@/components/kit/badge";
import { Stagger, StaggerItem } from "@/components/motion/reveal";
import { useT } from "@/i18n/client";
import { percent } from "@/lib/format";
import type { Material } from "@/lib/types";

import { KIND_KEYS, isWorking, type DocumentProgress } from "./model";

/** The course's files as a shelf of cards: a spine colour for the kind, the module, how readable the file is
 *  and, once practised, how well the student knows it. A card opens the preview. */
export function DocumentShelf({
  items,
  progress,
  selectedId,
  onOpen,
}: {
  items: Material[];
  progress: Map<string, DocumentProgress>;
  selectedId: string | null;
  onOpen: (material: Material) => void;
}) {
  const t = useT();
  return (
    <Stagger as="ul" className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
      {items.map((material) => {
        const info = progress.get(material.id);
        const working = isWorking(material);
        const spine = material.kind === "past_paper" ? "bg-warning" : material.kind === "note" ? "bg-accent" : "bg-primary";
        const Icon = material.mime_type?.startsWith("image/") ? ImageIcon : FileText;
        return (
          <StaggerItem as="li" key={material.id}>
            <button
              type="button"
              onClick={() => onOpen(material)}
              aria-pressed={selectedId === material.id}
              className={clsx(
                "glass-flat card-hover group relative flex h-full w-full flex-col gap-3 overflow-hidden rounded-2xl p-4 pl-5 text-left",
                selectedId === material.id && "border-primary/60 shadow-glow",
              )}
            >
              <span aria-hidden className={clsx("absolute inset-y-0 left-0 w-1.5", spine)} />
              <span className="flex items-start justify-between gap-2">
                <Icon className="h-5 w-5 shrink-0 text-muted group-hover:text-brand" strokeWidth={1.75} aria-hidden />
                <span className="flex flex-wrap justify-end gap-1">
                  <Badge>{t(KIND_KEYS[material.kind])}</Badge>
                  {material.status === "failed" ? <Badge tone="danger">{t("materials.status.failed")}</Badge> : null}
                  {working ? (
                    <Badge tone="info">
                      <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                      {t(`materials.status.${material.status}`)}
                    </Badge>
                  ) : null}
                </span>
              </span>
              <span className="min-w-0">
                <span className="block truncate text-[14px] font-medium group-hover:text-brand" title={material.filename}>
                  {material.filename}
                </span>
                <span className="block truncate text-xs text-muted">{material.module ?? t("sj.module.none")}</span>
              </span>
              {info && info.accuracy !== null ? (
                <span className="mt-auto flex items-center gap-2">
                  <Meter value={info.accuracy} tone={info.weak ? "danger" : "primary"} label={t("sj.col.accuracy")} className="flex-1" />
                  <span className={clsx("tabular text-xs", info.weak && "font-medium text-danger")}>{percent(info.accuracy)}</span>
                </span>
              ) : null}
            </button>
          </StaggerItem>
        );
      })}
    </Stagger>
  );
}
