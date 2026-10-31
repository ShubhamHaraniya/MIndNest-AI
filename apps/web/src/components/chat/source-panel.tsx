"use client";

import clsx from "clsx";
import { Download, ExternalLink, FileText, Folder, Loader2, X } from "lucide-react";
import Link from "next/link";
import { motion } from "motion/react";
import { useEffect, useId, useState } from "react";

import { Badge } from "@/components/kit/badge";
import { useT } from "@/i18n/client";
import { ApiError, api } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import type { Material, Source, Subject } from "@/lib/types";

type Tab = "passage" | "document";

const PREVIEWABLE = new Set(["application/pdf", "image/png", "image/jpeg", "text/plain"]);

/** Where an answer's evidence can be checked: the exact passage the answer used, the other
 *  sources of the same answer, and the file itself shown in a frame beside the conversation. */
export function SourcePanel({
  sources,
  activeN,
  subjects,
  onSelect,
  onClose,
}: {
  sources: Source[];
  activeN: number;
  subjects: Subject[];
  onSelect: (n: number) => void;
  onClose: () => void;
}) {
  const t = useT();
  const uid = useId();
  const source = sources.find((s) => s.n === activeN) ?? sources[0];
  const [material, setMaterial] = useState<Material | "missing" | null>(null);
  const [tab, setTab] = useState<Tab>("passage");
  const materialId = source?.material_id;

  useEffect(() => {
    if (!materialId) return;
    let cancelled = false;
    setMaterial(null);
    setTab("passage");
    (async () => {
      try {
        const found = await api<Material>(`/materials/${materialId}`);
        if (cancelled) return;
        setMaterial(found);
        // Inspecting a source counts as opening the file: it then shows under "recent documents".
        void api(`/materials/${materialId}/open`, { method: "POST" }).catch(() => undefined);
      } catch (caught) {
        if (!cancelled) setMaterial(caught instanceof ApiError && caught.status === 404 ? "missing" : "missing");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [materialId]);

  if (!source) return null;

  const file = material && material !== "missing" ? material : null;
  const course = file ? subjects.find((s) => s.id === file.subject_id) : undefined;
  const canPreview = file ? PREVIEWABLE.has(file.mime_type ?? "") : false;
  const frameSrc = file
    ? `/api/v1/materials/${file.id}/download?inline=true${file.mime_type === "application/pdf" && source.page ? `#page=${source.page}` : ""}`
    : null;
  const others = sources.filter((s) => s.n !== source.n);

  return (
    <aside aria-label={t("cw.panel.title", { n: source.n })} className="flex h-full min-h-0 flex-col">
      <header className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">
            {t("cw.panel.title", { n: source.n })}
          </p>
          <h2 className="mt-0.5 flex items-center gap-1.5 text-[13px] font-semibold leading-5">
            <FileText className="h-3.5 w-3.5 shrink-0 text-brand" aria-hidden />
            <span className="break-all">{source.filename}</span>
          </h2>
          <p className="mt-0.5 text-xs text-muted">
            {source.page !== null ? t("cw.panel.page", { n: source.page }) : t("cw.panel.noPage")}
            {course ? ` · ${course.name}` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("cw.panel.close")}
          className="shrink-0 rounded-lg p-1.5 text-muted hover:bg-surface-3 hover:text-ink"
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </header>

      <div role="tablist" aria-label={t("cw.panel.title", { n: source.n })} className="flex border-b border-border px-2">
        {(["passage", "document"] as const).map((id) => (
          <button
            key={id}
            role="tab"
            type="button"
            id={`source-tab-${id}`}
            aria-selected={tab === id}
            aria-controls="source-tabpanel"
            onClick={() => setTab(id)}
            className={clsx("relative h-10 px-3 text-[13px] font-medium", tab === id ? "text-ink" : "text-muted hover:text-ink")}
          >
            {t(id === "passage" ? "cw.panel.passage" : "cw.panel.document")}
            {tab === id ? (
              <motion.span
                layoutId={`${uid}-source-tab`}
                aria-hidden
                className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary shadow-glow"
                transition={{ type: "spring", stiffness: 420, damping: 36 }}
              />
            ) : null}
          </button>
        ))}
      </div>

      <div id="source-tabpanel" role="tabpanel" aria-labelledby={`source-tab-${tab}`} className="min-h-0 flex-1 overflow-y-auto">
        {tab === "passage" ? (
          <div className="space-y-4 p-4">
            <div>
              <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">
                {t("cw.panel.excerpt")}
              </p>
              <blockquote className="glass-flat font-display relative rounded-2xl border-s-2 border-s-primary px-4 py-3 text-[14px] font-normal leading-relaxed shadow-glow">
                {source.snippet}
              </blockquote>
            </div>

            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 border-t border-border pt-3 text-[13px]">
              {material === null ? (
                <p className="col-span-2 flex items-center gap-2 text-muted">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                  {t("cw.panel.loading")}
                </p>
              ) : file ? (
                <>
                  <div>
                    <dt className="text-[11px] text-faint">{t("cw.panel.type")}</dt>
                    <dd>{t(`materials.kind.${file.kind}`)}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] text-faint">{t("cw.panel.module")}</dt>
                    <dd className="truncate">{file.module ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] text-faint">{t("cw.panel.status")}</dt>
                    <dd>
                      <Badge tone={file.status === "ready" ? "success" : file.status === "failed" ? "danger" : "info"}>
                        {t(`materials.status.${file.status}`)}
                      </Badge>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[11px] text-faint">{t("cw.panel.size")}</dt>
                    <dd className="tabular">{formatBytes(file.size_bytes)}</dd>
                  </div>
                </>
              ) : (
                <p className="col-span-2 text-danger">{t("cw.panel.missing")}</p>
              )}
            </dl>

            {others.length > 0 ? (
              <div className="border-t border-border pt-3">
                <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">
                  {t("cw.panel.others")}
                </p>
                <ul className="space-y-1">
                  {others.map((other) => (
                    <li key={other.n}>
                      <button
                        type="button"
                        onClick={() => onSelect(other.n)}
                        className="flex w-full items-baseline gap-2 rounded-xl px-2 py-1.5 text-left text-[13px] hover:bg-surface-3/50"
                      >
                        <span className="w-5 shrink-0 font-semibold text-brand">[{other.n}]</span>
                        <span className="min-w-0 flex-1 truncate">{other.filename}</span>
                        <span className="shrink-0 text-xs text-muted">
                          {other.page !== null ? t("cw.panel.page", { n: other.page }) : ""}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : file && canPreview && frameSrc ? (
          file.mime_type?.startsWith("image/") ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={frameSrc} alt={file.filename} className="mx-auto max-w-full p-3" />
          ) : (
            <div className="h-full min-h-[24rem] p-3">
              <iframe key={frameSrc} src={frameSrc} title={file.filename} className="h-full min-h-[22rem] w-full rounded-2xl border border-border bg-surface-2" />
            </div>
          )
        ) : (
          <p className="p-4 text-[13px] text-muted">{file ? t("cw.panel.noPreview") : t("cw.panel.missing")}</p>
        )}
      </div>

      {file ? (
        <footer className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-4 py-2.5 text-xs">
          {canPreview ? (
            <a
              href={frameSrc ?? "#"}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 font-medium text-brand hover:underline"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              {t("cw.panel.open")}
            </a>
          ) : null}
          <a
            href={`/api/v1/materials/${file.id}/download`}
            className="flex items-center gap-1 font-medium text-brand hover:underline"
          >
            <Download className="h-3.5 w-3.5" aria-hidden />
            {t("chat.openFile")}
          </a>
          <Link
            href={`/subjects/${file.subject_id}?doc=${file.id}`}
            className="flex items-center gap-1 font-medium text-brand hover:underline"
          >
            <Folder className="h-3.5 w-3.5" aria-hidden />
            {t("cw.panel.course")}
          </Link>
        </footer>
      ) : null}
    </aside>
  );
}
