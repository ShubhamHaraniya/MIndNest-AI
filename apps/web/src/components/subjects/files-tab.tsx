"use client";

import clsx from "clsx";
import { FileUp, X } from "lucide-react";
import { useMemo, useState, type DragEvent, type ReactNode } from "react";

import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { Segmented, Select, SearchField } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { EmptyState, ErrorState, NoResults } from "@/components/kit/states";
import { Skeleton } from "@/components/kit/skeleton";
import { useT } from "@/i18n/client";
import type { Material, MaterialKind } from "@/lib/types";

import { DocumentShelf } from "./shelf";
import { DocumentsTable, sortMaterials, type Column, type RowAction, type Sort, type SortKey } from "./documents-table";
import { KINDS, KIND_KEYS, NO_MODULE, isWorking, type DocumentProgress } from "./model";
import type { Resource } from "./use-resource";

type StatusFilter = "all" | "ready" | "working" | "failed";

/** A searchable, filterable, sortable list of the course's files. The Documents tab shows every
 *  file; the Past papers and Notes tabs are the same list narrowed to one kind. */
export function FilesTab({
  kind,
  panelTitle,
  materials,
  progress,
  modules,
  moduleFilter,
  onModuleFilter,
  selectedId,
  compact,
  actions,
  empty,
  headerAction,
  above,
  onOpen,
  onEdit,
  onRetry,
  onDelete,
  onAsk,
  onUploadFiles,
  onUploadClick,
}: {
  /** Narrow to one kind (and hide the type filter), or null for every file. */
  kind: MaterialKind | null;
  panelTitle: string;
  materials: Resource<Material[]>;
  progress: Map<string, DocumentProgress>;
  modules: string[];
  moduleFilter: string;
  onModuleFilter: (value: string) => void;
  selectedId: string | null;
  /** The preview pane is open, so the table has less room. */
  compact: boolean;
  actions: RowAction[];
  empty: { title: string; description: string; extra?: ReactNode };
  /** Buttons for the panel's header: upload, write a note. */
  headerAction?: ReactNode;
  above?: ReactNode;
  onOpen: (material: Material) => void;
  onEdit: (material: Material) => void;
  onRetry: (material: Material) => void;
  onDelete: (material: Material) => void;
  onAsk: (material: Material) => void;
  onUploadFiles: (files: File[]) => void;
  onUploadClick: () => void;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [kindFilter, setKindFilter] = useState<MaterialKind | "all">("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [sort, setSort] = useState<Sort>({ key: "created", dir: "desc" });
  const [dragging, setDragging] = useState(false);
  const [layout, setLayout] = useState<"table" | "shelf">("table");

  const all = useMemo(() => (materials.data ?? []).filter((m) => (kind ? m.kind === kind : true)), [materials.data, kind]);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = all.filter((m) => {
      if (needle && !`${m.filename} ${m.module ?? ""}`.toLowerCase().includes(needle)) return false;
      if (!kind && kindFilter !== "all" && m.kind !== kindFilter) return false;
      if (moduleFilter === NO_MODULE ? m.module !== null : moduleFilter && m.module !== moduleFilter) return false;
      if (status === "ready" && m.status !== "ready") return false;
      if (status === "working" && !isWorking(m)) return false;
      if (status === "failed" && m.status !== "failed") return false;
      return true;
    });
    return sortMaterials(filtered, sort, progress);
  }, [all, query, kind, kindFilter, moduleFilter, status, sort, progress]);

  const filtering = query.trim() !== "" || kindFilter !== "all" || moduleFilter !== "" || status !== "all";
  // With the preview pane open the table is narrow: module and type move under the file name.
  const base: Column[] = compact
    ? ["status", "accuracy"]
    : ["module", "kind", "status", "accuracy", "language", "size", "created", "opened"];
  const columns = kind ? base.filter((column) => column !== "kind") : base;

  function toggleSort(key: SortKey) {
    setSort((current) =>
      current.key === key
        ? { key, dir: current.dir === "asc" ? "desc" : "asc" }
        : { key, dir: key === "created" || key === "opened" || key === "size" || key === "accuracy" ? "desc" : "asc" },
    );
  }

  function clearFilters() {
    setQuery("");
    setKindFilter("all");
    setStatus("all");
    onModuleFilter("");
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) onUploadFiles(files);
  }

  if (materials.error && !materials.data) {
    return <ErrorState description={materials.error} onRetry={materials.reload} compact />;
  }

  const showTable = !materials.loading && all.length > 0;
  return (
    <div className="space-y-3">
      {above}
      {all.length > 0 || materials.loading ? (
        <div className="flex flex-wrap items-center gap-2">
          <SearchField
            value={query}
            onChange={setQuery}
            placeholder={t("sj.files.search")}
            className="w-full sm:w-56"
          />
          {!kind ? (
            <Select
              aria-label={t("sj.col.type")}
              value={kindFilter}
              onChange={(event) => setKindFilter(event.target.value as MaterialKind | "all")}
              className="max-w-[9rem]"
            >
              <option value="all">{t("sj.filter.allTypes")}</option>
              {KINDS.map((value) => (
                <option key={value} value={value}>
                  {t(KIND_KEYS[value])}
                </option>
              ))}
            </Select>
          ) : null}
          <Select
            aria-label={t("sj.col.module")}
            value={moduleFilter}
            onChange={(event) => onModuleFilter(event.target.value)}
            className="max-w-[10rem]"
          >
            <option value="">{t("sj.filter.allModules")}</option>
            {modules.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
            <option value={NO_MODULE}>{t("sj.module.none")}</option>
          </Select>
          <Select
            aria-label={t("sj.col.status")}
            value={status}
            onChange={(event) => setStatus(event.target.value as StatusFilter)}
            className="max-w-[9rem]"
          >
            <option value="all">{t("sj.filter.allStatuses")}</option>
            <option value="ready">{t("materials.status.ready")}</option>
            <option value="working">{t("sj.filter.working")}</option>
            <option value="failed">{t("materials.status.failed")}</option>
          </Select>
          {filtering ? (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              <X className="h-3.5 w-3.5" aria-hidden />
              {t("sj.filter.clear")}
            </Button>
          ) : null}
        </div>
      ) : null}

      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={clsx(dragging && "outline outline-1 outline-offset-2 outline-primary")}
      >
        <Panel
          id={`files-${kind ?? "all"}`}
          title={panelTitle}
          description={
            showTable ? (
              <span aria-live="polite">{t("sj.files.count", { shown: shown.length, total: all.length })}</span>
            ) : undefined
          }
          action={
            <span className="flex items-center gap-2">
              {showTable ? (
                <Segmented
                  label={t("sj.view.label")}
                  value={layout}
                  onChange={setLayout}
                  options={[
                    { value: "table", label: t("sj.view.table") },
                    { value: "shelf", label: t("sj.view.cards") },
                  ]}
                />
              ) : null}
              {showTable && all.some(isWorking) ? (
                <Badge tone="info">{t("sj.files.reading", { count: all.filter(isWorking).length })}</Badge>
              ) : null}
              {headerAction}
            </span>
          }
        >
          {materials.loading ? (
            <div className="space-y-3 p-3.5" aria-hidden>
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-4 w-full" />
              ))}
            </div>
          ) : all.length === 0 ? (
            <div className="px-4 py-8">
              <EmptyState compact icon={FileUp} title={empty.title} description={empty.description}>
                {empty.extra}
                <Button variant={empty.extra ? "secondary" : "primary"} onClick={onUploadClick}>
                  <FileUp className="h-4 w-4" aria-hidden />
                  {t("sj.upload.button")}
                </Button>
              </EmptyState>
            </div>
          ) : shown.length === 0 ? (
            <div className="px-4 py-6">
              <NoResults title={t("sj.files.noResults")} description={t("sj.files.noResultsHelp")}>
                <Button variant="secondary" onClick={clearFilters}>
                  {t("sj.filter.clear")}
                </Button>
              </NoResults>
            </div>
          ) : layout === "shelf" ? (
            <DocumentShelf items={shown} progress={progress} selectedId={selectedId} onOpen={onOpen} />
          ) : (
            <DocumentsTable
              caption={panelTitle}
              items={shown}
              progress={progress}
              columns={columns}
              compact={compact}
              kindFixed={kind !== null}
              sort={sort}
              onSort={toggleSort}
              selectedId={selectedId}
              actions={actions}
              onOpen={onOpen}
              onEdit={onEdit}
              onRetry={onRetry}
              onDelete={onDelete}
              onAsk={onAsk}
            />
          )}
        </Panel>
      </div>
    </div>
  );
}
