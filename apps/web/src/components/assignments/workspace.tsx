"use client";

import { ChevronLeft, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { DraftEditor } from "@/components/assignments/draft-editor";
import { FeedbackTab } from "@/components/assignments/feedback-tab";
import { OverviewTab, type WorkTab } from "@/components/assignments/overview-tab";
import { DueCell, StatusBadge } from "@/components/assignments/parts";
import { LanguagePicker } from "@/components/assignments/run-parts";
import { BriefTab, FilesTab, HelpTab, HistoryTab, RubricTab } from "@/components/assignments/side-panels";
import { useDraftAutosave } from "@/components/assignments/use-autosave";
import { useFileDrop } from "@/components/assignments/use-file-drop";
import { useAssignmentUploads } from "@/components/assignments/use-uploads";
import { Button } from "@/components/kit/button";
import { ConfirmDialog } from "@/components/kit/confirm";
import { Tabs, type TabItem } from "@/components/kit/tabs";
import { PageSkeleton } from "@/components/kit/skeleton";
import { useToast } from "@/components/kit/toast";
import { Alert } from "@/components/ui";
import { useLocale, useT } from "@/i18n/client";
import { ApiError, api } from "@/lib/api";
import { AnimatedRing } from "@/components/motion/ring";
import { isWorking, readiness, workspaceError } from "@/lib/assignments";
import type { AssignmentDetail, AssignmentRun, HelpKind, Language, Rubric, Subject } from "@/lib/types";

const POLL_MS = 3000;
const TABS: WorkTab[] = ["overview", "files", "instructions", "rubric", "help", "feedback", "history"];
const parseTab = (value: string | null): WorkTab => (TABS as string[]).includes(value ?? "") ? (value as WorkTab) : "overview";

/** One assignment: the student's draft in the middle, and beside it the brief, rubric, files,
 *  AI help and history. Loads the assignment, then hands it to the editor below. */
export function AssignmentWorkspace({ assignmentId, subjects }: { assignmentId: string; subjects: Subject[] }) {
  const t = useT();
  const [detail, setDetail] = useState<AssignmentDetail | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const loaded = await api<AssignmentDetail>(`/assignments/${assignmentId}`);
      setDetail(loaded);
      setError(null);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 404) setMissing(true);
      else setError(workspaceError(caught, t));
    }
  }, [assignmentId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const back = (
    <Link href="/assignments" className="mb-3 inline-flex items-center gap-1 text-[13px] text-muted hover:text-ink">
      <ChevronLeft className="h-4 w-4" aria-hidden />
      {t("assign.detail.back")}
    </Link>
  );

  if (missing) {
    return (
      <>
        {back}
        <Alert>{t("errors.not_found")}</Alert>
      </>
    );
  }
  if (!detail) {
    return (
      <>
        {back}
        {error ? <Alert>{error}</Alert> : <PageSkeleton label={t("common.loading")} />}
      </>
    );
  }
  return <Editor detail={detail} setDetail={setDetail} reload={load} subjects={subjects} back={back} />;
}

function Editor({
  detail,
  setDetail,
  reload,
  subjects,
  back,
}: {
  detail: AssignmentDetail;
  setDetail: (detail: AssignmentDetail) => void;
  reload: () => Promise<void>;
  subjects: Subject[];
  back: React.ReactNode;
}) {
  const t = useT();
  const locale = useLocale();
  const router = useRouter();
  const toast = useToast();
  const pathname = usePathname();
  const search = useSearchParams();
  const [tab, setTabState] = useState<WorkTab>(() => parseTab(search.get("tab")));
  // The tab lives in the address, so a link opens the same view and a reload keeps it.
  const setTab = useCallback(
    (next: WorkTab) => {
      setTabState(next);
      const params = new URLSearchParams(window.location.search);
      if (next === "overview") params.delete("tab");
      else params.set("tab", next);
      const query = params.toString();
      window.history.replaceState(null, "", query ? `${pathname}?${query}` : pathname);
    },
    [pathname],
  );
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState<Language>(locale);
  const [starting, setStarting] = useState<HelpKind | null>(null);
  const [historyKey, setHistoryKey] = useState(0);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const uploads = useAssignmentUploads({
    assignmentId: detail.id,
    attached: detail.files.length,
    hasCourse: detail.subject_id !== null,
    onUploaded: () => void reload(),
  });
  const drop = useFileDrop((files) => {
    setTab("files");
    void uploads.upload(files);
  });

  const { draft, setDraft, status, savedAt, saveNow, reset } = useDraftAutosave({
    initial: detail.draft,
    save: async (text) => {
      try {
        await api<AssignmentDetail>(`/assignments/${detail.id}`, { method: "PATCH", body: { draft: text } });
        setHistoryKey((key) => key + 1);
        return true;
      } catch {
        return false;
      }
    },
  });

  // Look again while any help is being written.
  const working = detail.latest_runs.some((run) => isWorking(run.status));
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => void reload(), POLL_MS);
    return () => clearInterval(timer);
  }, [working, reload]);

  async function ask(kind: HelpKind) {
    setError(null);
    setStarting(kind);
    try {
      // Feedback is about the draft as written, so it is saved first.
      if (kind === "feedback" && !(await saveNow())) {
        setError(t("asw.draft.error"));
        return;
      }
      await api(`/assignments/${detail.id}/runs`, { method: "POST", body: { kind, language } });
      setTab(kind === "feedback" ? "feedback" : "help");
      await reload();
      setHistoryKey((key) => key + 1);
    } catch (caught) {
      setError(workspaceError(caught, t));
    } finally {
      setStarting(null);
    }
  }

  async function saveVersion(note: string): Promise<boolean> {
    if (!(await saveNow())) {
      setError(t("asw.draft.error"));
      return false;
    }
    try {
      await api(`/assignments/${detail.id}/revisions`, { method: "POST", body: { note } });
      toast.success(t("aw.history.versionSaved"));
      setHistoryKey((key) => key + 1);
      return true;
    } catch (caught) {
      setError(workspaceError(caught, t));
      return false;
    }
  }

  function blockedFor(kind: HelpKind): string | null {
    if (kind === "feedback") return draft.trim() ? null : t("assign.detail.needDraft");
    return detail.has_brief || detail.files.length > 0 ? null : t("assign.detail.needBrief");
  }

  async function remove() {
    await api(`/assignments/${detail.id}`, { method: "DELETE" });
    router.push("/assignments");
  }

  const setup = readiness(detail);
  const setupRatio = setup.length > 0 ? setup.filter((item) => item.done).length / setup.length : 0;

  const tabs: TabItem<WorkTab>[] = [
    { id: "overview", label: t("aw2.tab.overview") },
    { id: "files", label: t("aw.tab.files"), count: detail.files.length || undefined },
    { id: "instructions", label: t("aw2.tab.instructions") },
    { id: "rubric", label: t("aw.tab.rubric"), count: detail.rubric?.criteria.length || undefined },
    { id: "help", label: t("aw2.tab.help") },
    { id: "feedback", label: t("aw2.tab.feedback") },
    { id: "history", label: t("aw.tab.history"), count: detail.revision_count || undefined },
  ];

  function go(target: WorkTab | "draft") {
    if (target === "draft") document.getElementById("assignment-draft")?.focus();
    else setTab(target);
  }

  return (
    <div {...drop.bind} className="relative">
      {drop.dragging ? (
        <div
          aria-hidden
          className="glass-strong pointer-events-none absolute inset-0 z-20 flex items-center justify-center rounded-3xl border-2 border-dashed border-primary/60 shadow-glow"
        >
          <p className="flex items-center gap-2 text-sm font-medium text-brand">
            <Upload className="h-4 w-4" />
            {detail.subject_id === null ? t("aw2.drop.needCourse") : t("aw2.drop.release")}
          </p>
        </div>
      ) : null}
      {back}
      <header className="glass sheen mb-4 flex flex-wrap items-center justify-between gap-3 rounded-3xl px-4 py-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-4">
          <AnimatedRing value={setupRatio} size={60} stroke={5} label={t("aw2.ov.setup")}>
            <span className="tabular text-xs font-semibold">{Math.round(setupRatio * 100)}%</span>
          </AnimatedRing>
          <div className="min-w-0">
            <h1 className="font-display text-2xl leading-tight sm:text-3xl">{detail.title}</h1>
            <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
              <StatusBadge status={detail.status} />
              <span className="text-muted">{detail.subject_name ?? t("assign.create.anySubject")}</span>
              <DueCell dueAt={detail.due_at} status={detail.status} locale={locale} inline />
            </p>
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)}>
          <Trash2 className="h-4 w-4" aria-hidden />
          {t("assign.detail.delete")}
        </Button>
      </header>

      {error ? (
        <div className="mb-3">
          <Alert>{error}</Alert>
        </div>
      ) : null}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_24rem] xl:grid-cols-[minmax(0,1fr)_27rem]">
        <DraftEditor
          value={draft}
          onChange={setDraft}
          status={status}
          savedAt={savedAt}
          onSaveNow={() => void saveNow()}
          onSaveVersion={saveVersion}
          onFeedback={() => void ask("feedback")}
          feedbackBusy={starting === "feedback"}
        />

        <aside className="glass rounded-3xl lg:sticky lg:top-3">
          <div className="flex items-center justify-between gap-2 border-b border-border px-3.5">
            <Tabs items={tabs} value={tab} onChange={setTab} label={t("aw.tabs")} className="border-b-0" />
            {tab === "help" || tab === "feedback" ? <LanguagePicker value={language} onChange={setLanguage} /> : null}
          </div>
          <div role="tabpanel" className="max-h-[calc(100dvh-9rem)] overflow-y-auto">
            {tab === "overview" ? <OverviewTab detail={detail} onSaved={setDetail} onGo={go} /> : null}
            {tab === "instructions" ? <BriefTab key={detail.updated_at} detail={detail} subjects={subjects} onSaved={setDetail} /> : null}
            {tab === "rubric" ? (
              <RubricTab detail={detail} onSaved={(rubric: Rubric | null) => setDetail({ ...detail, rubric, has_rubric: rubric !== null })} />
            ) : null}
            {tab === "files" ? <FilesTab detail={detail} uploads={uploads} onChanged={() => void reload()} /> : null}
            {tab === "help" ? (
              <HelpTab
                detail={detail}
                runs={detail.latest_runs as AssignmentRun[]}
                kinds={["breakdown", "outline"]}
                starting={starting}
                blockedFor={blockedFor}
                onAsk={(kind) => void ask(kind)}
              />
            ) : null}
            {tab === "feedback" ? (
              <FeedbackTab detail={detail} starting={starting === "feedback"} blocked={blockedFor("feedback")} onAsk={() => void ask("feedback")} />
            ) : null}
            {tab === "history" ? (
              <HistoryTab
                detail={detail}
                refreshKey={historyKey}
                onRestored={(restored) => {
                  setDetail(restored);
                  reset(restored.draft);
                  toast.success(t("aw.history.restored"));
                  setHistoryKey((key) => key + 1);
                }}
              />
            ) : null}
          </div>
        </aside>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title={t("assign.detail.delete")}
        description={t("assign.detail.deleteConfirm", { name: detail.title })}
        confirmLabel={t("assign.detail.delete")}
        onClose={() => setConfirmDelete(false)}
        onConfirm={remove}
      />
    </div>
  );
}
