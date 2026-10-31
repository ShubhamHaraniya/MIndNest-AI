"use client";

import clsx from "clsx";
import { FileUp, PenLine } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/kit/button";
import { Tabs } from "@/components/kit/tabs";
import { useToast } from "@/components/kit/toast";
import { setCourseCookie } from "@/components/shell/course";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Assignment, Material, MaterialKind, Subject } from "@/lib/types";

import { AnalyticsTab } from "./analytics-tab";
import { AssignmentsTab } from "./assignments-tab";
import { CourseFormDialog } from "./course-dialogs";
import { CourseHeader } from "./course-header";
import type { RowAction } from "./documents-table";
import { FilesTab } from "./files-tab";
import { useMaterialActions } from "./material-actions";
import {
  NO_MODULE,
  POLL_MS,
  isWorking,
  naturalCompare,
  parseTab,
  type CourseAnalytics,
  type CourseOverview,
  type CourseProgress,
  type DocumentProgress,
  type QuizBrief,
  type TabId,
} from "./model";
import { ModulesTab } from "./modules-tab";
import { NoteEditor } from "./note-editor";
import { OverviewTab } from "./overview-tab";
import { PreviewPane } from "./preview-pane";
import { QuizzesTab } from "./quizzes-tab";
import { UploadDialog } from "./upload-dialog";
import { useResource } from "./use-resource";

const FILE_ACTIONS: RowAction[] = ["retry", "preview", "download", "edit", "delete"];
const PAPER_ACTIONS: RowAction[] = ["retry", "preview", "ask", "download", "edit", "delete"];

/** One course: its header, six tabs (overview, documents, past papers, notes, quizzes, topic
 *  progress) and a preview pane for the file in `?doc=`. The tab, the open file and the module
 *  filter live in the address so every view can be linked to and survives a reload. */
export function CourseWorkspace({ initial, currentId }: { initial: Subject; currentId: string | null }) {
  const t = useT();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();

  const [course, setCourse] = useState<Subject>(initial);
  const id = course.id;
  const tab = parseTab(search.get("tab"));
  const docId = search.get("doc");
  const pageParam = Number(search.get("page"));
  const page = Number.isInteger(pageParam) && pageParam > 0 ? pageParam : null;
  const moduleFilter = search.get("module") ?? "";

  const materials = useResource<Material[]>(`/subjects/${id}/materials`);
  const overview = useResource<CourseOverview>(`/subjects/${id}/overview`);
  const progress = useResource<CourseProgress>(`/subjects/${id}/progress`);
  // Used by the overview ("recommended next") and by the analytics tab.
  const analytics = useResource<CourseAnalytics>(`/subjects/${id}/analytics`);
  const assignments = useResource<Assignment[]>(tab === "assignments" ? `/subjects/${id}/assignments` : null);
  const [quizzesWanted, setQuizzesWanted] = useState(tab === "quizzes");
  const quizzes = useResource<QuizBrief[]>(quizzesWanted ? "/quizzes" : null);
  useEffect(() => {
    if (tab === "quizzes") setQuizzesWanted(true);
  }, [tab]);

  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadKind, setUploadKind] = useState<MaterialKind>("material");
  const [uploadModule, setUploadModule] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [writing, setWriting] = useState(false);

  // ------------------------------------------------------------------------ address state
  const setParams = useCallback(
    (changes: Record<string, string | null>) => {
      const next = new URLSearchParams(search.toString());
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === "") next.delete(key);
        else next.set(key, value);
      }
      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [pathname, router, search],
  );

  const openDoc = useCallback((docToOpen: string, pageNumber: number | null = null) => setParams({ doc: docToOpen, page: pageNumber ? String(pageNumber) : null }), [setParams]);
  const closeDoc = useCallback(() => setParams({ doc: null, page: null }), [setParams]);
  const showTab = (next: TabId) => setParams({ tab: next === "overview" ? null : next });
  const showModule = (module: string | null) => setParams({ tab: "documents", module });

  // ------------------------------------------------------------------- files and polling
  const files = materials.data;
  const working = files?.some(isWorking) ?? false;
  useEffect(() => {
    if (!working) return;
    const timer = setTimeout(materials.reload, POLL_MS);
    return () => clearTimeout(timer);
  }, [working, files, materials.reload]);

  // When the last file finishes being read, the course's figures (ready counts, accuracy) have changed.
  const wasWorking = useRef(false);
  useEffect(() => {
    if (wasWorking.current && !working) {
      overview.reload();
      progress.reload();
      analytics.reload();
    }
    wasWorking.current = working;
  }, [working, overview.reload, progress.reload, analytics.reload]); // eslint-disable-line react-hooks/exhaustive-deps

  const modules = useMemo(
    () => [...new Set((files ?? []).map((m) => m.module).filter((m): m is string => m !== null))].sort(naturalCompare),
    [files],
  );
  const progressByDoc = useMemo(() => {
    const map = new Map<string, DocumentProgress>();
    for (const doc of progress.data?.documents ?? []) if (doc.material_id) map.set(doc.material_id, doc);
    return map;
  }, [progress.data]);

  function refreshFigures() {
    overview.reload();
    progress.reload();
    analytics.reload();
  }

  const actions = useMaterialActions({
    materials,
    modules,
    onChanged: refreshFigures,
    onRemoved: (removed) => {
      if (removed.id === docId) closeDoc();
    },
  });

  // ------------------------------------------------------------------------- the open file
  const selected = files?.find((m) => m.id === docId) ?? null;
  const opened = useRef(new Set<string>());
  const selectedId = selected?.id;
  useEffect(() => {
    if (!selectedId || opened.current.has(selectedId)) return;
    opened.current.add(selectedId);
    api(`/materials/${selectedId}/open`, { method: "POST" })
      .then(() => {
        const now = new Date().toISOString();
        materials.setData((list) => list.map((m) => (m.id === selectedId ? { ...m, last_opened_at: now } : m)));
      })
      .catch(() => undefined);
  }, [selectedId, materials]);

  // On a wide screen the pane sticks beside the table; bring it fully into view when a file is opened.
  const paneBox = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!docId || !paneBox.current) return;
    if (!window.matchMedia("(min-width: 1024px)").matches) return;
    if (paneBox.current.getBoundingClientRect().top > 140) paneBox.current.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [docId]);

  // ------------------------------------------------------------------------------ actions
  function ask() {
    setCourseCookie(id);
    router.refresh(); // the sidebar shows the course the chat will use
    router.push("/chat");
  }

  function makeCurrent() {
    setCourseCookie(id);
    router.refresh();
    toast.success(t("sj.list.nowCurrent", { name: course.name }));
  }

  async function toggleArchive() {
    try {
      const saved = await api<Subject>(`/subjects/${id}/${course.archived_at ? "unarchive" : "archive"}`, { method: "POST" });
      setCourse(saved);
      overview.reload();
      router.refresh();
      toast.success(t(saved.archived_at ? "sj.list.archived" : "sj.list.restored", { name: saved.name }));
    } catch (caught) {
      toast.error(errorMessage(caught, t));
    }
  }

  async function saveDescription(description: string | null) {
    try {
      setCourse(await api<Subject>(`/subjects/${id}`, { method: "PATCH", body: { description } }));
    } catch (caught) {
      toast.error(errorMessage(caught, t));
      throw caught;
    }
  }

  function openUpload(kind: MaterialKind, withFiles: File[] = [], module: string | null = null) {
    setUploadKind(kind);
    setUploadModule(module);
    setUploadFiles(withFiles);
    setUploadOpen(true);
  }
  const kindForTab: MaterialKind = tab === "papers" ? "past_paper" : tab === "notes" ? "note" : "material";
  const realModule = moduleFilter && moduleFilter !== NO_MODULE ? moduleFilter : "";

  const counts = {
    documents: files?.length,
    papers: files?.filter((m) => m.kind === "past_paper").length,
    notes: files?.filter((m) => m.kind === "note").length,
    quizzes: overview.data?.course.quizzes,
  };

  const common = {
    materials,
    progress: progressByDoc,
    modules,
    moduleFilter,
    onModuleFilter: (value: string) => setParams({ module: value }),
    selectedId: docId,
    compact: docId !== null,
    onOpen: (material: Material) => openDoc(material.id),
    onEdit: actions.edit,
    onRetry: (material: Material) => void actions.retry(material),
    onDelete: actions.remove,
    onAsk: ask,
    onUploadFiles: (dropped: File[]) => openUpload(kindForTab, dropped),
    onUploadClick: () => openUpload(kindForTab),
  };

  return (
    <div className="space-y-4">
      <CourseHeader
        course={course}
        figures={overview.data?.course ?? null}
        summary={progress.data?.summary ?? null}
        isCurrent={currentId === id}
        onAsk={ask}
        onUpload={() => openUpload(kindForTab)}
        onEdit={() => setEditOpen(true)}
        onMakeCurrent={makeCurrent}
        onToggleArchive={() => void toggleArchive()}
        onSaveDescription={saveDescription}
      />

      <Tabs
        label={course.name}
        value={tab}
        onChange={showTab}
        items={[
          { id: "overview", label: t("sj.tab.overview") },
          { id: "modules", label: t("sj.tab.modules"), count: progress.data ? progress.data.modules.filter((m) => m.module !== null).length : undefined },
          { id: "documents", label: t("sj.tab.documents"), count: counts.documents },
          { id: "notes", label: t("sj.tab.notes"), count: counts.notes },
          { id: "papers", label: t("sj.tab.papers"), count: counts.papers },
          { id: "quizzes", label: t("sj.tab.quizzes"), count: counts.quizzes },
          { id: "assignments", label: t("sj.tab.assignments"), count: assignments.data ? assignments.data.filter((a) => a.status !== "done").length : undefined },
          { id: "analytics", label: t("sj.tab.analytics") },
        ]}
      />

      <div className={clsx("grid gap-4", docId && "lg:grid-cols-[minmax(0,1fr)_25rem] xl:grid-cols-[minmax(0,1fr)_30rem]")}>
        <div role="tabpanel" aria-label={t(`sj.tab.${tab}`)} className="min-w-0">
          {tab === "overview" ? (
            <OverviewTab
              subjectId={id}
              overview={overview}
              progress={progress}
              analytics={analytics}
              materials={materials}
              onOpenModule={showModule}
              onOpenDoc={(target) => openDoc(target)}
              onShowProgress={() => showTab("analytics")}
              onShowMaterials={() => showTab("documents")}
              onUpload={() => openUpload("material")}
            />
          ) : null}
          {tab === "modules" ? (
            <ModulesTab
              subjectId={id}
              courseName={course.name}
              progress={progress}
              onOpenModule={showModule}
              onUpload={(module) => openUpload("material", [], module || null)}
              onChanged={() => {
                materials.reload();
                refreshFigures();
              }}
            />
          ) : null}
          {tab === "documents" ? (
            <FilesTab
              {...common}
              kind={null}
              panelTitle={t("sj.tab.documents")}
              actions={FILE_ACTIONS}
              empty={{ title: t("materials.emptyTitle"), description: t("materials.emptyBody") }}
              headerAction={
                <Button size="sm" onClick={() => openUpload("material")}>
                  <FileUp className="h-3.5 w-3.5" aria-hidden />
                  {t("sj.upload.button")}
                </Button>
              }
            />
          ) : null}
          {tab === "papers" ? (
            <FilesTab
              {...common}
              kind="past_paper"
              panelTitle={t("sj.tab.papers")}
              actions={PAPER_ACTIONS}
              above={<p className="max-w-2xl text-[13px] text-muted">{t("sj.papers.intro")}</p>}
              empty={{ title: t("sj.papers.emptyTitle"), description: t("sj.papers.emptyBody") }}
              headerAction={
                <Button size="sm" onClick={() => openUpload("past_paper")}>
                  <FileUp className="h-3.5 w-3.5" aria-hidden />
                  {t("sj.papers.upload")}
                </Button>
              }
            />
          ) : null}
          {tab === "notes" ? (
            <FilesTab
              {...common}
              kind="note"
              panelTitle={t("sj.tab.notes")}
              actions={PAPER_ACTIONS}
              above={
                writing ? (
                  <NoteEditor
                    subjectId={id}
                    modules={modules}
                    defaultModule={realModule}
                    onCancel={() => setWriting(false)}
                    onSaved={(saved) => {
                      setWriting(false);
                      materials.setData((list) => [saved, ...list]);
                      materials.reload();
                      refreshFigures();
                      openDoc(saved.id);
                    }}
                  />
                ) : null
              }
              empty={{
                title: t("sj.notes.emptyTitle"),
                description: t("sj.notes.emptyBody"),
                extra: (
                  <Button onClick={() => setWriting(true)}>
                    <PenLine className="h-4 w-4" aria-hidden />
                    {t("sj.note.title")}
                  </Button>
                ),
              }}
              headerAction={
                <>
                  {!writing ? (
                    <Button size="sm" onClick={() => setWriting(true)}>
                      <PenLine className="h-3.5 w-3.5" aria-hidden />
                      {t("sj.note.title")}
                    </Button>
                  ) : null}
                  <Button size="sm" variant="secondary" onClick={() => openUpload("note")}>
                    <FileUp className="h-3.5 w-3.5" aria-hidden />
                    {t("sj.upload.button")}
                  </Button>
                </>
              }
            />
          ) : null}
          {tab === "quizzes" ? (
            <QuizzesTab
              quizzes={quizzes}
              course={overview.data?.course ?? null}
              subjectId={id}
              readyDocuments={overview.data?.course.documents_ready ?? 0}
            />
          ) : null}
          {tab === "assignments" ? (
            <AssignmentsTab subjectId={id} assignments={assignments} onChanged={() => overview.reload()} />
          ) : null}
          {tab === "analytics" ? (
            <AnalyticsTab
              analytics={analytics}
              figures={overview.data?.course ?? null}
              progress={progress}
              subjectId={id}
              onOpenDoc={(target) => openDoc(target)}
              onOpenModule={showModule}
              onAsk={ask}
            />
          ) : null}
        </div>

        {docId ? (
          <div ref={paneBox} className="min-w-0 lg:sticky lg:top-3 lg:self-start">
            <PreviewPane
              material={selected}
              state={materials.loading ? "loading" : selected ? "ready" : "missing"}
              page={page}
              info={selected ? progressByDoc.get(selected.id) : undefined}
              moduleCount={modules.length}
              onClose={closeDoc}
              onEdit={actions.edit}
              onDelete={actions.remove}
              onAsk={ask}
            />
          </div>
        ) : null}
      </div>

      {actions.dialogs}
      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        subjectId={id}
        defaultKind={uploadKind}
        defaultModule={uploadModule ?? realModule}
        initialFiles={uploadFiles}
        modules={modules}
        onUploaded={() => {
          materials.reload();
          refreshFigures();
        }}
      />
      <CourseFormDialog
        open={editOpen}
        course={course}
        onClose={() => setEditOpen(false)}
        onSaved={(saved) => {
          setCourse(saved);
          setEditOpen(false);
          overview.reload();
          router.refresh();
          toast.success(t("sj.list.saved", { name: saved.name }));
        }}
      />
    </div>
  );
}
