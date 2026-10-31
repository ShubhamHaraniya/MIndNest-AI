"use client";

import clsx from "clsx";
import { Download, Eye, FileText, MessageSquare, Pencil, RotateCcw, Trash2 } from "lucide-react";

import { Badge } from "@/components/kit/badge";
import { Table, TBody, THead, Td, Th, Tr } from "@/components/kit/table";
import { useLocale, useT } from "@/i18n/client";
import { LOCALE_NAMES } from "@/i18n/config";
import { bcp47, formatBytes, relativeTime } from "@/lib/format";
import type { Material } from "@/lib/types";

import { AccuracyCell, IconButton, IconLink, SortTh, StatusCell, failureReason } from "./bits";
import { KIND_KEYS, downloadUrl, isStale, naturalCompare, type DocumentProgress } from "./model";

export type Column = "module" | "kind" | "status" | "language" | "size" | "created" | "opened" | "accuracy";
export type SortKey = "name" | Column;
export type Sort = { key: SortKey; dir: "asc" | "desc" };
export type RowAction = "preview" | "download" | "ask" | "edit" | "retry" | "delete";

/** Which breakpoint each column appears at, so a phone shows only the name and what matters most. */
const VISIBILITY: Record<Column, string> = {
  module: "hidden md:table-cell",
  kind: "hidden sm:table-cell",
  status: "",
  language: "hidden xl:table-cell",
  size: "hidden lg:table-cell",
  created: "hidden lg:table-cell",
  opened: "hidden xl:table-cell",
  accuracy: "hidden md:table-cell",
};

const STATUS_ORDER = { failed: 0, uploaded: 1, processing: 2, ready: 3 } as const;

export function sortMaterials(items: Material[], sort: Sort, progress: Map<string, DocumentProgress>): Material[] {
  const direction = sort.dir === "asc" ? 1 : -1;
  const time = (value: string | null) => (value ? Date.parse(value) : 0);
  const key = (m: Material): string | number => {
    switch (sort.key) {
      case "name":
        return m.filename;
      case "module":
        return m.module ?? "";
      case "kind":
        return m.kind;
      case "status":
        return STATUS_ORDER[m.status];
      case "language":
        return m.language ?? "";
      case "size":
        return m.size_bytes ?? 0;
      case "created":
        return time(m.created_at);
      case "opened":
        return time(m.last_opened_at);
      case "accuracy":
        return progress.get(m.id)?.accuracy ?? -1;
    }
  };
  return [...items].sort((a, b) => {
    const x = key(a);
    const y = key(b);
    // Files without a module (or never opened) sort last whichever way the column runs.
    if (sort.key === "module" && (x === "") !== (y === "")) return x === "" ? 1 : -1;
    const order = typeof x === "number" && typeof y === "number" ? x - y : naturalCompare(String(x), String(y));
    return order * direction || naturalCompare(a.filename, b.filename);
  });
}

export function DocumentsTable({
  items,
  progress,
  columns,
  compact,
  kindFixed,
  sort,
  onSort,
  selectedId,
  actions,
  onOpen,
  onEdit,
  onRetry,
  onDelete,
  onAsk,
  caption,
}: {
  items: Material[];
  progress: Map<string, DocumentProgress>;
  columns: Column[];
  /** The preview pane is open: type and module are shown under the name instead of in columns. */
  compact: boolean;
  /** The list holds a single kind (past papers, notes), so the type is never repeated. */
  kindFixed: boolean;
  sort: Sort;
  onSort: (key: SortKey) => void;
  selectedId: string | null;
  actions: RowAction[];
  onOpen: (material: Material) => void;
  onEdit: (material: Material) => void;
  onRetry: (material: Material) => void;
  onDelete: (material: Material) => void;
  onAsk?: (material: Material) => void;
  caption: string;
}) {
  const t = useT();
  const locale = useLocale();
  const has = (column: Column) => columns.includes(column);
  const header = (key: SortKey, label: string, className?: string, align?: "left" | "right") => (
    <SortTh label={label} active={sort.key === key} dir={sort.dir} onSort={() => onSort(key)} className={className} align={align} />
  );
  const dateFormat = new Intl.DateTimeFormat(bcp47(locale), { day: "numeric", month: "short", year: "numeric" });

  return (
    <Table caption={caption}>
      <THead>
        <tr>
          {header("name", t("sj.col.name"), "w-full min-w-[12rem]")}
          {has("module") ? header("module", t("sj.col.module"), VISIBILITY.module) : null}
          {has("kind") ? header("kind", t("sj.col.type"), VISIBILITY.kind) : null}
          {has("status") ? header("status", t("sj.col.status"), VISIBILITY.status) : null}
          {has("accuracy") ? header("accuracy", t("sj.col.accuracy"), VISIBILITY.accuracy) : null}
          {has("language") ? header("language", t("sj.col.language"), VISIBILITY.language) : null}
          {has("size") ? header("size", t("sj.col.size"), VISIBILITY.size, "right") : null}
          {has("created") ? header("created", t("sj.col.added"), VISIBILITY.created) : null}
          {has("opened") ? header("opened", t("sj.col.opened"), VISIBILITY.opened) : null}
          <Th align="right">
            <span className="sr-only">{t("sj.col.actions")}</span>
          </Th>
        </tr>
      </THead>
      <TBody>
        {items.map((material) => {
          const reason = failureReason(t, material);
          const info = progress.get(material.id);
          const canRetry = material.status === "failed" || isStale(material);
          const selected = material.id === selectedId;
          return (
            <Tr
              key={material.id}
              aria-selected={selected}
              className={clsx(selected && "bg-primary-soft hover:bg-primary-soft")}
            >
              <Td className="max-w-0">
                <button
                  type="button"
                  onClick={() => onOpen(material)}
                  title={material.filename}
                  className="flex w-full min-w-0 items-start gap-2 text-left hover:text-brand"
                >
                  <FileText className="mt-0.5 h-4 w-4 shrink-0 text-faint" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{material.filename}</span>
                    {reason ? (
                      <span className="mt-0.5 block text-xs font-normal text-danger">{reason}</span>
                    ) : (
                      <span className="flex min-w-0 gap-x-2 text-xs font-normal text-muted">
                        {!kindFixed ? (
                          <span className={clsx("shrink-0", compact ? "" : "sm:hidden")}>{t(KIND_KEYS[material.kind])}</span>
                        ) : null}
                        {material.module ? <span className={clsx("truncate", compact ? "" : "md:hidden")}>{material.module}</span> : null}
                      </span>
                    )}
                  </span>
                </button>
              </Td>
              {has("module") ? (
                <Td className={clsx("max-w-[11rem]", VISIBILITY.module)}>
                  {material.module ? (
                    <span className="block truncate" title={material.module}>
                      {material.module}
                    </span>
                  ) : (
                    <span className="text-faint">{t("sj.module.none")}</span>
                  )}
                </Td>
              ) : null}
              {has("kind") ? (
                <Td className={clsx("whitespace-nowrap", VISIBILITY.kind)}>
                  <Badge>{t(KIND_KEYS[material.kind])}</Badge>
                </Td>
              ) : null}
              {has("status") ? (
                <Td className={clsx("w-36 max-w-[10rem]", VISIBILITY.status)}>
                  <StatusCell material={material} />
                </Td>
              ) : null}
              {has("accuracy") ? (
                <Td className={clsx("whitespace-nowrap", VISIBILITY.accuracy)}>
                  <AccuracyCell
                    accuracy={info?.accuracy ?? null}
                    answers={info?.answers ?? 0}
                    weak={info?.weak ?? false}
                    label={t("sj.progress.accuracyOf", { name: material.filename })}
                  />
                </Td>
              ) : null}
              {has("language") ? (
                <Td className={clsx("whitespace-nowrap text-muted", VISIBILITY.language)}>
                  {material.language ? LOCALE_NAMES[material.language] : "—"}
                </Td>
              ) : null}
              {has("size") ? (
                <Td align="right" className={clsx("tabular whitespace-nowrap text-muted", VISIBILITY.size)}>
                  {formatBytes(material.size_bytes)}
                </Td>
              ) : null}
              {has("created") ? (
                <Td className={clsx("whitespace-nowrap text-muted", VISIBILITY.created)}>
                  <time dateTime={material.created_at} title={dateFormat.format(new Date(material.created_at))}>
                    {relativeTime(material.created_at, locale)}
                  </time>
                </Td>
              ) : null}
              {has("opened") ? (
                <Td className={clsx("whitespace-nowrap text-muted", VISIBILITY.opened)}>
                  {material.last_opened_at ? (
                    <time dateTime={material.last_opened_at}>{relativeTime(material.last_opened_at, locale)}</time>
                  ) : (
                    <span className="text-faint">{t("sj.opened.never")}</span>
                  )}
                </Td>
              ) : null}
              <Td align="right" className="whitespace-nowrap">
                <span className="inline-flex items-center justify-end gap-0.5">
                  {actions.includes("retry") && canRetry ? (
                    <IconButton label={t("materials.retry")} onClick={() => onRetry(material)}>
                      <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                    </IconButton>
                  ) : null}
                  {actions.includes("preview") ? (
                    <IconButton label={t("sj.action.preview")} onClick={() => onOpen(material)}>
                      <Eye className="h-3.5 w-3.5" aria-hidden />
                    </IconButton>
                  ) : null}
                  {actions.includes("ask") && onAsk ? (
                    <IconButton label={t("sj.action.askAbout")} onClick={() => onAsk(material)} className="hidden sm:inline-flex">
                      <MessageSquare className="h-3.5 w-3.5" aria-hidden />
                    </IconButton>
                  ) : null}
                  {actions.includes("download") ? (
                    <span className="hidden sm:inline-flex">
                      <IconLink download label={t("materials.download")} href={downloadUrl(material.id)}>
                        <Download className="h-3.5 w-3.5" aria-hidden />
                      </IconLink>
                    </span>
                  ) : null}
                  {actions.includes("edit") ? (
                    <IconButton label={t("sj.action.edit")} onClick={() => onEdit(material)}>
                      <Pencil className="h-3.5 w-3.5" aria-hidden />
                    </IconButton>
                  ) : null}
                  {actions.includes("delete") ? (
                    <IconButton label={t("materials.delete")} danger onClick={() => onDelete(material)}>
                      <Trash2 className="h-3.5 w-3.5" aria-hidden />
                    </IconButton>
                  ) : null}
                </span>
              </Td>
            </Tr>
          );
        })}
      </TBody>
    </Table>
  );
}
