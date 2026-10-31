"use client";

import { BookMarked, Download, Eye, FileText, FolderPlus, Flag, Info, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { InstitutionField } from "@/components/library/institution-field";
import { AddDialog, PreviewDialog, ReportDialog } from "@/components/library/item-dialogs";
import { PublishDialog } from "@/components/library/publish-dialog";
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  NoResults,
  Panel,
  SearchField,
  Segmented,
  Select,
  Skeleton,
  Table,
  TBody,
  Td,
  Th,
  THead,
  Tr,
  buttonClass,
  useToast,
  Tabs,
} from "@/components/kit";
import { Alert } from "@/components/ui";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { RIGHTS_KEYS, formatSize } from "@/lib/groups";
import {
  DOC_TYPES,
  DOC_TYPE_KEYS,
  PAGE_SIZE,
  SCOPES,
  SCOPE_HELP_KEYS,
  SCOPE_KEYS,
  STATUS_KEYS,
  STATUS_TONES,
  VISIBILITY_KEYS,
  fileUrl,
} from "@/lib/library";
import type { LibraryDocType, LibraryFacets, LibraryItem, LibraryPage, LibraryScope, User } from "@/lib/types";

type Filters = {
  q: string;
  docType: LibraryDocType | "";
  course: string;
  topic: string;
  semester: string;
  year: string;
  institution: string;
  sort: "newest" | "title";
};

const NO_FILTERS: Filters = { q: "", docType: "", course: "", topic: "", semester: "", year: "", institution: "", sort: "newest" };
const NO_FACETS: LibraryFacets = { courses: [], topics: [], semesters: [], years: [], institutions: [] };

function queryString(scope: LibraryScope, filters: Filters, offset: number): string {
  const params = new URLSearchParams({ scope, sort: filters.sort, limit: String(PAGE_SIZE), offset: String(offset) });
  if (filters.q.trim()) params.set("q", filters.q.trim());
  if (filters.docType) params.set("doc_type", filters.docType);
  if (filters.course) params.set("course", filters.course);
  if (filters.topic) params.set("topic", filters.topic);
  if (filters.semester) params.set("semester", filters.semester);
  if (filters.year) params.set("year", filters.year);
  if (filters.institution) params.set("institution", filters.institution);
  return params.toString();
}

/** Notes, past papers and other files shared beyond a study group: by college, across colleges,
 *  or openly. Everything shown here was published on purpose by its owner. */
export function MaterialsLibrary({ user, initialScope }: { user: User; initialScope?: string }) {
  const t = useT();
  const toast = useToast();
  const start: LibraryScope = SCOPES.includes(initialScope as LibraryScope) ? (initialScope as LibraryScope) : "college";
  const [scope, setScope] = useState<LibraryScope>(start);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<LibraryPage | null>(null);
  const [facets, setFacets] = useState<LibraryFacets>(NO_FACETS);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);

  const [preview, setPreview] = useState<LibraryItem | null>(null);
  const [adding, setAdding] = useState<LibraryItem | null>(null);
  const [reporting, setReporting] = useState<LibraryItem | null>(null);
  const [editing, setEditing] = useState<LibraryItem | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [removing, setRemoving] = useState<LibraryItem | null>(null);

  // The search box feeds the query after a short pause, so typing does not fire a request per key.
  const searchTimer = useRef<number | null>(null);
  function onSearch(value: string) {
    setSearch(value);
    if (searchTimer.current) window.clearTimeout(searchTimer.current);
    searchTimer.current = window.setTimeout(() => {
      setFilters((current) => ({ ...current, q: value }));
      setOffset(0);
    }, 300);
  }
  useEffect(() => () => {
    if (searchTimer.current) window.clearTimeout(searchTimer.current);
  }, []);

  function changeScope(next: LibraryScope) {
    setScope(next);
    setFilters(NO_FILTERS);
    setSearch("");
    setOffset(0);
    window.history.replaceState(null, "", `?scope=${next}`);
  }

  function setFilter<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters((current) => ({ ...current, [key]: value }));
    setOffset(0);
  }

  // The list for this tab, filters and page.
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api<LibraryPage>(`/library?${queryString(scope, filters, offset)}`, { signal: controller.signal })
      .then((result) => {
        setPage(result);
        setError(null);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setError(errorMessage(caught, t));
        setLoading(false);
      });
    return () => controller.abort();
  }, [scope, filters, offset, reload, t]);

  // The values to filter by come from what the tab really holds.
  useEffect(() => {
    api<LibraryFacets>(`/library/facets?scope=${scope}`)
      .then(setFacets)
      .catch(() => setFacets(NO_FACETS));
  }, [scope, reload]);

  const refresh = useCallback(() => setReload((n) => n + 1), []);
  const items = page?.items ?? [];
  const total = page?.total ?? 0;
  const filtered = useMemo(
    () => Object.entries(filters).some(([key, value]) => key !== "sort" && value !== ""),
    [filters],
  );
  const myInstitution = page?.my_institution ?? user.institution_name;

  async function remove(item: LibraryItem) {
    try {
      await api(`/library/${item.id}`, { method: "DELETE" });
      toast.success(t("ml.deleted"));
      refresh();
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  const tabs = SCOPES.map((id) => ({
    id,
    label: t(SCOPE_KEYS[id]),
    count: scope === id && page && !filtered ? total : undefined,
  }));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-surface px-4 py-3.5 shadow-card sm:px-5">
        <div className="flex min-w-0 max-w-2xl items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-brand">
            <BookMarked className="h-5 w-5" strokeWidth={1.75} aria-hidden />
          </span>
          <p className="pt-0.5 text-sm text-muted">{t("ml.intro")}</p>
        </div>
        <Button onClick={() => setPublishing(true)}>
          <Plus className="h-3.5 w-3.5" aria-hidden />
          {t("ml.publish.button")}
        </Button>
      </div>

      <Tabs items={tabs} value={scope} onChange={changeScope} label={t("ml.tabs")} />
      <p className="flex items-start gap-2 text-xs text-muted">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        {t(SCOPE_HELP_KEYS[scope])}
      </p>

      {scope === "college" && !myInstitution ? <CollegePrompt initial={myInstitution} /> : null}

      <FilterBar
        scope={scope}
        filters={filters}
        search={search}
        facets={facets}
        onSearch={onSearch}
        onFilter={setFilter}
        onClear={() => {
          setFilters((current) => ({ ...NO_FILTERS, sort: current.sort }));
          setSearch("");
          setOffset(0);
        }}
        active={filtered}
      />

      {error ? (
        <ErrorState description={error} onRetry={refresh} compact />
      ) : loading && page === null ? (
        <Panel title={t(SCOPE_KEYS[scope])} bodyClassName="p-3.5">
          <div className="space-y-2" aria-busy="true" aria-label={t("common.loading")}>
            {[0, 1, 2, 3].map((n) => (
              <Skeleton key={n} className="h-9 w-full" />
            ))}
          </div>
        </Panel>
      ) : items.length === 0 ? (
        filtered ? (
          <NoResults title={t("ml.noResults")} description={t("ml.noResultsBody")} />
        ) : (
          <EmptyState title={t(`ml.empty.${scope}` as const)} description={t(`ml.empty.${scope}.body` as const)}>
            {scope === "mine" ? (
              <Button onClick={() => setPublishing(true)}>{t("ml.publish.button")}</Button>
            ) : null}
          </EmptyState>
        )
      ) : (
        <Panel
          title={t(SCOPE_KEYS[scope])}
          description={t("ml.count", { count: total })}
          bodyClassName={loading ? "opacity-60 transition-opacity" : undefined}
          footer={
            total > PAGE_SIZE ? (
              <div className="flex items-center justify-between gap-3">
                <span className="tabular">
                  {t("ml.range", { from: offset + 1, to: Math.min(offset + PAGE_SIZE, total), total })}
                </span>
                <span className="flex gap-2">
                  <Button size="sm" variant="secondary" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                    {t("common.previous")}
                  </Button>
                  <Button size="sm" variant="secondary" disabled={offset + PAGE_SIZE >= total || loading} onClick={() => setOffset(offset + PAGE_SIZE)}>
                    {t("common.next")}
                  </Button>
                </span>
              </div>
            ) : undefined
          }
        >
          <Table caption={t(SCOPE_KEYS[scope])}>
            <THead>
              <tr>
                <Th>{t("ml.col.file")}</Th>
                <Th>{t("ml.col.type")}</Th>
                <Th>{t("ml.col.course")}</Th>
                <Th>{t("ml.col.term")}</Th>
                <Th>{t("ml.col.source")}</Th>
                <Th>{scope === "mine" ? t("ml.col.status") : t("ml.col.licence")}</Th>
                <Th align="right">
                  <span className="sr-only">{t("ml.col.actions")}</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {items.map((item) => (
                <Row
                  key={item.id}
                  item={item}
                  showStatus={scope === "mine"}
                  onPreview={() => setPreview(item)}
                  onAdd={() => setAdding(item)}
                  onReport={() => setReporting(item)}
                  onEdit={() => setEditing(item)}
                  onRemove={() => setRemoving(item)}
                />
              ))}
            </TBody>
          </Table>
        </Panel>
      )}

      <PreviewDialog item={preview} onClose={() => setPreview(null)} />
      <AddDialog
        item={adding}
        onClose={() => setAdding(null)}
        onDone={() => {
          setAdding(null);
          toast.success(t("ml.add.done"));
        }}
      />
      <ReportDialog
        item={reporting}
        onClose={() => setReporting(null)}
        onDone={(held) => {
          setReporting(null);
          toast.success(held ? t("ml.report.held") : t("lib.report.done"));
          refresh();
        }}
      />
      <PublishDialog
        open={publishing || editing !== null}
        user={{ ...user, institution_name: myInstitution }}
        item={editing}
        onClose={() => {
          setPublishing(false);
          setEditing(null);
        }}
        onSaved={(saved) => {
          toast.success(saved.status === "pending_review" ? t("ml.saved.review") : t("ml.saved"));
          if (!editing) changeScope("mine");
          refresh();
        }}
      />
      <ConfirmDialog
        open={removing !== null}
        title={t("ml.delete.title")}
        description={t("ml.delete.body")}
        confirmLabel={t("ml.delete.confirm")}
        onConfirm={async () => {
          if (removing) await remove(removing);
        }}
        onClose={() => setRemoving(null)}
      />
    </div>
  );
}

function FilterBar({
  scope,
  filters,
  search,
  facets,
  onSearch,
  onFilter,
  onClear,
  active,
}: {
  scope: LibraryScope;
  filters: Filters;
  search: string;
  facets: LibraryFacets;
  onSearch: (value: string) => void;
  onFilter: <K extends keyof Filters>(key: K, value: Filters[K]) => void;
  onClear: () => void;
  active: boolean;
}) {
  const t = useT();
  const choices = (label: string, value: string, values: string[], key: keyof Filters) => (
    <label className="block min-w-[8.5rem]">
      <span className="sr-only">{label}</span>
      <Select
        className="w-full"
        aria-label={label}
        value={value}
        disabled={values.length === 0 && value === ""}
        onChange={(event) => onFilter(key, event.target.value as never)}
      >
        <option value="">{label}</option>
        {values.map((v) => (
          <option key={v} value={v}>
            {v}
          </option>
        ))}
      </Select>
    </label>
  );

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-card border border-border bg-surface p-3 shadow-card" role="search" aria-label={t("ml.filters")}>
      <SearchField className="w-full sm:w-64" value={search} onChange={onSearch} placeholder={t("ml.search")} />
      <label className="block min-w-[8.5rem]">
        <span className="sr-only">{t("ml.field.type")}</span>
        <Select
          className="w-full"
          aria-label={t("ml.field.type")}
          value={filters.docType}
          onChange={(event) => onFilter("docType", event.target.value as LibraryDocType | "")}
        >
          <option value="">{t("ml.field.type")}</option>
          {DOC_TYPES.map((type) => (
            <option key={type} value={type}>
              {t(DOC_TYPE_KEYS[type])}
            </option>
          ))}
        </Select>
      </label>
      {choices(t("ml.field.course"), filters.course, facets.courses, "course")}
      {choices(t("ml.field.topic"), filters.topic, facets.topics, "topic")}
      {choices(t("ml.field.semester"), filters.semester, facets.semesters, "semester")}
      {choices(t("ml.field.year"), filters.year, facets.years, "year")}
      {scope !== "college" ? choices(t("ml.field.institution"), filters.institution, facets.institutions, "institution") : null}
      <Segmented
        label={t("ml.sort")}
        value={filters.sort}
        onChange={(value) => onFilter("sort", value)}
        options={[
          { value: "newest", label: t("ml.sort.newest") },
          { value: "title", label: t("ml.sort.title") },
        ]}
      />
      {active ? (
        <Button size="sm" variant="ghost" onClick={onClear}>
          {t("ml.clearFilters")}
        </Button>
      ) : null}
    </div>
  );
}

function Row({
  item,
  showStatus,
  onPreview,
  onAdd,
  onReport,
  onEdit,
  onRemove,
}: {
  item: LibraryItem;
  showStatus: boolean;
  onPreview: () => void;
  onAdd: () => void;
  onReport: () => void;
  onEdit: () => void;
  onRemove: () => void;
}) {
  const t = useT();
  const locked = item.status === "held" || item.status === "taken_down";
  const readable = item.status === "published" || item.mine;
  return (
    <Tr>
      <Td className="max-w-[22rem]">
        <div className="flex items-start gap-3">
          <span aria-hidden className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-brand">
            <FileText className="h-4 w-4" strokeWidth={1.75} />
          </span>
          <div className="min-w-0">
            <p className="truncate font-medium" title={item.title}>
              {item.title}
            </p>
            <p className="truncate text-xs text-muted" title={item.filename}>
              {item.filename}
              {item.size_bytes !== null ? ` · ${formatSize(item.size_bytes)}` : ""}
            </p>
            {item.description ? <p className="line-clamp-1 text-xs text-muted">{item.description}</p> : null}
          </div>
        </div>
      </Td>
      <Td>
        <Badge>{t(DOC_TYPE_KEYS[item.doc_type])}</Badge>
      </Td>
      <Td className="max-w-[12rem]">
        <p className="truncate" title={item.course_name}>
          {item.course_name || "—"}
        </p>
        {item.topic ? <p className="truncate text-xs text-muted">{item.topic}</p> : null}
      </Td>
      <Td className="whitespace-nowrap text-muted">
        {[item.semester ? t("ml.semesterShort", { value: item.semester }) : "", item.academic_year].filter(Boolean).join(" · ") || "—"}
      </Td>
      <Td className="max-w-[12rem]">
        <p className="truncate" title={item.institution}>
          {item.institution || t("ml.noInstitution")}
        </p>
        {item.author ? <p className="truncate text-xs text-muted">{t("ml.by", { author: item.author })}</p> : null}
      </Td>
      <Td>
        {showStatus ? (
          <div className="space-y-1">
            <Badge tone={STATUS_TONES[item.status]}>{t(STATUS_KEYS[item.status])}</Badge>
            <p className="text-xs text-muted">{t(VISIBILITY_KEYS[item.visibility])}</p>
            {item.status === "rejected" && item.review_note ? (
              <p className="max-w-[12rem] text-xs text-warning">{item.review_note}</p>
            ) : null}
          </div>
        ) : (
          <span className="text-xs text-muted">{t(RIGHTS_KEYS[item.rights])}</span>
        )}
      </Td>
      <Td align="right">
        <div className="flex items-center justify-end gap-0.5">
          {readable && item.previewable ? (
            <IconButton label={t("ml.action.preview")} onClick={onPreview}>
              <Eye className="h-4 w-4" aria-hidden />
            </IconButton>
          ) : null}
          {readable && item.status !== "taken_down" ? (
            <a
              href={fileUrl(item.id)}
              aria-label={`${t("lib.file.download")}: ${item.title}`}
              title={t("lib.file.download")}
              className={buttonClass("ghost", "sm", "px-1.5")}
            >
              <Download className="h-4 w-4" aria-hidden />
            </a>
          ) : null}
          {readable && !locked ? (
            <IconButton label={t("ml.action.add")} onClick={onAdd}>
              <FolderPlus className="h-4 w-4" aria-hidden />
            </IconButton>
          ) : null}
          {item.mine ? (
            <>
              {!locked ? (
                <IconButton label={t("ml.action.edit")} onClick={onEdit}>
                  <Pencil className="h-4 w-4" aria-hidden />
                </IconButton>
              ) : null}
              <IconButton label={t("ml.action.delete")} onClick={onRemove}>
                <Trash2 className="h-4 w-4" aria-hidden />
              </IconButton>
            </>
          ) : (
            <IconButton label={item.reported_by_me ? t("ml.action.reported") : t("ml.action.report")} onClick={onReport} disabled={item.reported_by_me}>
              <Flag className="h-4 w-4" aria-hidden />
            </IconButton>
          )}
        </div>
      </Td>
    </Tr>
  );
}

function IconButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <Button size="sm" variant="ghost" className="px-1.5" onClick={onClick} disabled={disabled} aria-label={label} title={label}>
      {children}
    </Button>
  );
}

/** "My college" needs an institution; ask for it right where the empty list would be confusing. */
function CollegePrompt({ initial }: { initial: string }) {
  const t = useT();
  const toast = useToast();
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      await api("/me", { method: "PATCH", body: { institution_name: value.trim() } });
      toast.success(t("inst.saved"));
      // The signed-in user is read on the server, so reload to pick the new institution up everywhere.
      window.location.reload();
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Alert tone="info">
      <p className="font-medium">{t("ml.college.needTitle")}</p>
      <p className="mt-0.5 text-xs">{t("ml.college.needBody")}</p>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <div className="min-w-[16rem] flex-1">
          <InstitutionField value={value} onChange={setValue} id="ml-college" />
        </div>
        <Button onClick={() => void save()} loading={busy} disabled={value.trim().length < 2}>
          {t("common.save")}
        </Button>
        <Link href="/settings?tab=account" className="pb-2 text-xs text-brand underline-offset-2 hover:underline">
          {t("ml.college.settings")}
        </Link>
      </div>
    </Alert>
  );
}
