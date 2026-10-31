"use client";

import clsx from "clsx";
import { Download, ExternalLink, MessageSquare, Pencil, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Markdown } from "@/components/markdown";
import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { Skeleton } from "@/components/kit/skeleton";
import { useLocale, useT } from "@/i18n/client";
import { LOCALE_NAMES } from "@/i18n/config";
import { bcp47, formatBytes, percent, relativeTime } from "@/lib/format";
import type { Material } from "@/lib/types";

import { StatusCell, failureReason, microLabel } from "./bits";
import { KIND_KEYS, downloadUrl, inlineUrl, previewMode, type DocumentProgress } from "./model";

type View = "preview" | "details";
const TEXT_LIMIT = 200_000;

/** The file open beside the table: the file itself when a browser can show it, and always its
 *  details (type, module, status, size, quiz accuracy) and the actions that apply to it. */
export function PreviewPane({
  material,
  state,
  page,
  info,
  moduleCount,
  onClose,
  onEdit,
  onDelete,
  onAsk,
}: {
  material: Material | null;
  /** "loading" while the course's files are still loading, "missing" when the id is not in this course. */
  state: "ready" | "loading" | "missing";
  page: number | null;
  info: DocumentProgress | undefined;
  moduleCount: number;
  onClose: () => void;
  onEdit: (material: Material) => void;
  onDelete: (material: Material) => void;
  onAsk: (material: Material) => void;
}) {
  const t = useT();
  const mode = material ? previewMode(material) : "none";
  const [view, setView] = useState<View>("preview");

  // A new file starts on its preview, or on its details when there is nothing to show.
  const id = material?.id;
  useEffect(() => {
    setView(mode === "none" ? "details" : "preview");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  const shown: View = mode === "none" ? "details" : view;

  return (
    <aside
      aria-label={t("sj.preview.title")}
      className="fixed inset-0 z-50 flex flex-col bg-surface lg:static lg:z-auto lg:h-[calc(100dvh-9.5rem)] lg:min-h-[26rem] lg:rounded-card lg:border lg:border-border"
    >
      <header className="flex items-start justify-between gap-2 border-b border-border px-3.5 py-2.5">
        <div className="min-w-0">
          <p className={microLabel()}>{t("sj.preview.title")}</p>
          {material ? (
            <>
              <h2 className="mt-0.5 break-all text-[13px] font-semibold leading-5">{material.filename}</h2>
              <p className="mt-0.5 text-xs text-muted">
                {[t(KIND_KEYS[material.kind]), material.module, formatBytes(material.size_bytes)].filter(Boolean).join(" · ")}
              </p>
            </>
          ) : (
            <Skeleton className="mt-1.5 h-4 w-40" />
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("sj.preview.close")}
          className="shrink-0 rounded p-1 text-muted hover:bg-surface-3 hover:text-ink"
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      </header>

      {material ? (
        <>
          <div role="tablist" aria-label={t("sj.preview.title")} className="flex border-b border-border px-2">
            {mode !== "none" ? (
              <ViewTab id="preview" current={shown} onSelect={setView} label={t("sj.preview.tabPreview")} />
            ) : null}
            <ViewTab id="details" current={shown} onSelect={setView} label={t("sj.preview.tabDetails")} />
          </div>

          <div role="tabpanel" className="min-h-0 flex-1 overflow-y-auto bg-surface">
            {shown === "preview" ? (
              <Body material={material} mode={mode} page={page} />
            ) : (
              <Details material={material} info={info} moduleCount={moduleCount} />
            )}
          </div>

          <footer className="flex flex-wrap items-center gap-1.5 border-t border-border px-3 py-2">
            <Button size="sm" variant="secondary" onClick={() => onAsk(material)}>
              <MessageSquare className="h-3.5 w-3.5" aria-hidden />
              {t("sj.action.askAbout")}
            </Button>
            <a
              href={downloadUrl(material.id)}
              className="inline-flex h-7 items-center gap-1.5 rounded border border-border-strong bg-surface px-2.5 text-xs font-medium hover:bg-surface-2"
            >
              <Download className="h-3.5 w-3.5" aria-hidden />
              {t("materials.download")}
            </a>
            {mode === "pdf" || mode === "image" ? (
              <a
                href={`${inlineUrl(material.id)}${mode === "pdf" && page ? `#page=${page}` : ""}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex h-7 items-center gap-1.5 rounded px-2 text-xs font-medium text-brand hover:bg-surface-3"
              >
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                {t("cw.panel.open")}
              </a>
            ) : null}
            <span className="ml-auto flex gap-0.5">
              <Button size="sm" variant="ghost" onClick={() => onEdit(material)} aria-label={t("sj.action.edit")} title={t("sj.action.edit")}>
                <Pencil className="h-3.5 w-3.5" aria-hidden />
              </Button>
              <Button size="sm" variant="ghost" onClick={() => onDelete(material)} aria-label={t("materials.delete")} title={t("materials.delete")}>
                <Trash2 className="h-3.5 w-3.5 text-danger" aria-hidden />
              </Button>
            </span>
          </footer>
        </>
      ) : (
        <div className="p-4 text-[13px]">
          {state === "loading" ? (
            <div className="space-y-2" aria-hidden>
              <Skeleton className="h-3.5 w-full" />
              <Skeleton className="h-3.5 w-2/3" />
            </div>
          ) : (
            <p role="alert" className="text-danger">
              {t("sj.preview.missing")}
            </p>
          )}
        </div>
      )}
    </aside>
  );
}

function ViewTab({ id, current, onSelect, label }: { id: View; current: View; onSelect: (view: View) => void; label: string }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={current === id}
      onClick={() => onSelect(id)}
      className={clsx(
        "-mb-px h-9 border-b-2 px-2.5 text-[13px] font-medium",
        current === id ? "border-primary text-ink" : "border-transparent text-muted hover:text-ink",
      )}
    >
      {label}
    </button>
  );
}

function Body({ material, mode, page }: { material: Material; mode: ReturnType<typeof previewMode>; page: number | null }) {
  const t = useT();
  if (mode === "pdf") {
    const src = `${inlineUrl(material.id)}${page ? `#page=${page}` : ""}`;
    return <iframe key={src} src={src} title={material.filename} className="h-full min-h-[24rem] w-full border-0 bg-surface-2" />;
  }
  if (mode === "image") {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={inlineUrl(material.id)} alt={material.filename} className="mx-auto max-w-full p-3" />;
  }
  if (mode === "markdown" || mode === "text") return <TextBody material={material} markdown={mode === "markdown"} />;
  return <p className="p-4 text-[13px] text-muted">{t("cw.panel.noPreview")}</p>;
}

/** Plain text and Markdown files are read here and shown as text, since the server only frames PDFs and images. */
function TextBody({ material, markdown }: { material: Material; markdown: boolean }) {
  const t = useT();
  const [text, setText] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const id = material.id;

  useEffect(() => {
    let cancelled = false;
    setText(null);
    setFailed(false);
    fetch(downloadUrl(id), { credentials: "same-origin" })
      .then((response) => (response.ok ? response.text() : Promise.reject(new Error(String(response.status)))))
      .then((body) => {
        if (!cancelled) setText(body);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (failed) return <p className="p-4 text-[13px] text-danger">{t("sj.preview.readFailed")}</p>;
  if (text === null) {
    return (
      <div className="space-y-2 p-4" aria-hidden>
        <Skeleton className="h-3.5 w-full" />
        <Skeleton className="h-3.5 w-5/6" />
        <Skeleton className="h-3.5 w-2/3" />
      </div>
    );
  }
  const clipped = text.length > TEXT_LIMIT;
  const body = clipped ? text.slice(0, TEXT_LIMIT) : text;
  return (
    <div className="p-4 text-[14px]">
      {markdown ? (
        <Markdown text={body} citations={[]} streaming={false} onCite={() => undefined} />
      ) : (
        <pre className="whitespace-pre-wrap break-words font-sans leading-relaxed">{body}</pre>
      )}
      {clipped ? <p className="mt-3 text-xs text-muted">{t("sj.preview.clipped")}</p> : null}
    </div>
  );
}

function Details({ material, info, moduleCount }: { material: Material; info: DocumentProgress | undefined; moduleCount: number }) {
  const t = useT();
  const locale = useLocale();
  const day = new Intl.DateTimeFormat(bcp47(locale), { day: "numeric", month: "short", year: "numeric" });
  const reason = failureReason(t, material);
  const rows: { label: string; value: string }[] = [
    { label: t("sj.col.type"), value: t(KIND_KEYS[material.kind]) },
    { label: t("sj.col.module"), value: material.module ?? (moduleCount > 0 ? t("sj.module.none") : "—") },
    { label: t("sj.col.size"), value: formatBytes(material.size_bytes) },
    { label: t("sj.col.language"), value: material.language ? LOCALE_NAMES[material.language] : "—" },
    { label: t("sj.col.added"), value: day.format(new Date(material.created_at)) },
    {
      label: t("sj.col.opened"),
      value: material.last_opened_at ? relativeTime(material.last_opened_at, locale) : t("sj.opened.never"),
    },
    { label: t("sj.detail.passages"), value: material.status === "ready" ? String(material.chunk_count) : "—" },
    { label: t("sj.detail.format"), value: material.mime_type ?? "—" },
  ];
  return (
    <div className="space-y-4 p-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-40">
          <StatusCell material={material} />
        </div>
        {reason ? <p className="text-[13px] text-danger">{reason}</p> : null}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-[13px]">
        {rows.map((row) => (
          <div key={row.label} className="min-w-0">
            <dt className={microLabel()}>{row.label}</dt>
            <dd className="tabular truncate" title={row.value}>
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
      <div className="border-t border-border pt-3">
        <p className={microLabel()}>{t("sj.col.accuracy")}</p>
        {info && info.answers > 0 && info.accuracy !== null ? (
          <p className="mt-1 flex flex-wrap items-center gap-2 text-[13px]">
            <span className={clsx("tabular text-base font-semibold", info.weak && "text-danger")}>{percent(info.accuracy)}</span>
            <span className="text-muted">{t("sj.progress.answers", { count: info.answers })}</span>
            {info.weak ? <Badge tone="danger">{t("sj.progress.weak")}</Badge> : null}
          </p>
        ) : (
          <p className="mt-1 text-[13px] text-muted">{t("sj.progress.notPractisedHelp")}</p>
        )}
      </div>
    </div>
  );
}
