"use client";

import { ClipboardList, FileText, Loader2, Paperclip, Plus, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { DueCell, StatusBadge } from "@/components/assignments/parts";
import { useFileDrop } from "@/components/assignments/use-file-drop";
import { Button } from "@/components/kit/button";
import { FormRow, Input, SearchField, Segmented, Select } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { Skeleton } from "@/components/kit/skeleton";
import { EmptyState, ErrorState, NoResults } from "@/components/kit/states";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/kit/table";
import { ACCEPTED_EXTENSIONS } from "@/components/subjects/model";
import { useToast } from "@/components/kit/toast";
import { PageHeader } from "@/components/page";
import { useLocale, useT } from "@/i18n/client";
import { api, uploadAssignmentFile } from "@/lib/api";
import { MAX_FILES, MAX_TITLE_CHARS, daysLeft, dueFromInput, isWorking, titleFromFile, workspaceError } from "@/lib/assignments";
import { relativeTime } from "@/lib/format";
import type { Assignment, AssignmentDetail, AssignmentStatus, Subject } from "@/lib/types";

const POLL_MS = 3000;
type StatusFilter = "open" | "all" | AssignmentStatus;
type DueFilter = "any" | "soon" | "overdue";

function isOverdue(item: Assignment): boolean {
  const days = daysLeft(item.due_at);
  return days !== null && days < 0 && item.status !== "done";
}

function isSoon(item: Assignment): boolean {
  const days = daysLeft(item.due_at);
  return days !== null && days >= 0 && days <= 7 && item.status !== "done";
}

export function AssignmentsHub({ subjects, courseId }: { subjects: Subject[]; courseId: string | null }) {
  const t = useT();
  const locale = useLocale();
  const [items, setItems] = useState<Assignment[] | null>(null);
  const [failed, setFailed] = useState(false);
  // The sidebar's course is where the list starts; "all courses" is one choice away.
  const [course, setCourse] = useState<string>(courseId ?? "all");
  const [status, setStatus] = useState<StatusFilter>("open");
  const [due, setDue] = useState<DueFilter>("any");
  const [query, setQuery] = useState("");
  const titleInput = useRef<HTMLInputElement>(null);

  useEffect(() => setCourse(courseId ?? "all"), [courseId]);

  const load = useCallback(async () => {
    try {
      setItems(await api<Assignment[]>("/assignments"));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const anyWorking = items?.some((item) => item.runs.some((run) => isWorking(run.status))) ?? false;
  useEffect(() => {
    if (!anyWorking) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [anyWorking, load]);

  const inCourse = useMemo(
    () => (items ?? []).filter((item) => course === "all" || item.subject_id === course),
    [items, course],
  );
  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return inCourse.filter((item) => {
      if (status === "open" ? item.status === "done" : status !== "all" && item.status !== status) return false;
      if (due === "overdue" && !isOverdue(item)) return false;
      if (due === "soon" && !isSoon(item)) return false;
      return needle === "" || item.title.toLowerCase().includes(needle);
    });
  }, [inCourse, status, due, query]);

  const counts = useMemo(
    () => ({
      open: inCourse.filter((item) => item.status !== "done").length,
      overdue: inCourse.filter(isOverdue).length,
      soon: inCourse.filter(isSoon).length,
    }),
    [inCourse],
  );
  const filtered = status !== "open" || due !== "any" || query.trim() !== "";

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("nav.assignments")}
        description={t("asl.intro")}
        help="assignments"
        actions={
          <Button size="sm" onClick={() => titleInput.current?.focus()}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
            {t("assign.create.button")}
          </Button>
        }
      />

      <QuickCreate subjects={subjects} course={course === "all" ? "" : course} inputRef={titleInput} />

      {items ? <DueNext items={inCourse} locale={locale} /> : null}

      <Panel
        id="assignments"
        title={t("assign.list.title")}
        description={
          items
            ? t("asl.summary", { open: counts.open, overdue: counts.overdue, soon: counts.soon })
            : undefined
        }
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-3.5 py-2">
          <SearchField value={query} onChange={setQuery} placeholder={t("asl.search")} className="w-full sm:w-56" />
          <label className="flex items-center gap-2 text-xs text-muted">
            <span className="sr-only sm:not-sr-only">{t("assign.create.subject")}</span>
            <Select
              value={course}
              onChange={(event) => setCourse(event.target.value)}
              className="h-8 max-w-[14rem] text-[13px]"
              aria-label={t("assign.create.subject")}
            >
              <option value="all">{t("cw.scopeAll")}</option>
              {subjects.map((subject) => (
                <option key={subject.id} value={subject.id}>
                  {subject.name}
                </option>
              ))}
            </Select>
          </label>
          <Segmented<StatusFilter>
            label={t("asl.filter.status")}
            value={status}
            onChange={setStatus}
            options={[
              { value: "open", label: t("asl.filter.open") },
              { value: "todo", label: t("assign.status.todo") },
              { value: "in_progress", label: t("assign.status.in_progress") },
              { value: "done", label: t("assign.status.done") },
              { value: "all", label: t("cw.filterAll") },
            ]}
          />
          <Segmented<DueFilter>
            label={t("asl.filter.due")}
            value={due}
            onChange={setDue}
            options={[
              { value: "any", label: t("asl.filter.anyDue") },
              { value: "soon", label: t("asl.filter.soon"), count: counts.soon },
              { value: "overdue", label: t("asl.filter.overdue"), count: counts.overdue },
            ]}
          />
        </div>

        {failed && items === null ? (
          <div className="p-4">
            <ErrorState compact onRetry={() => void load()} />
          </div>
        ) : items === null ? (
          <ListSkeleton label={t("common.loading")} />
        ) : items.length === 0 ? (
          <div className="p-4">
            <EmptyState compact icon={ClipboardList} title={t("asl.empty.title")} description={t("asl.empty.body")} />
          </div>
        ) : shown.length === 0 ? (
          <div className="p-4">
            <NoResults title={t("asl.none.title")} description={t("asl.none.body")}>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setStatus("all");
                  setDue("any");
                  setQuery("");
                  setCourse("all");
                }}
              >
                {t("asl.none.clear")}
              </Button>
            </NoResults>
          </div>
        ) : (
          <Table caption={t("assign.list.title")}>
            <THead>
              <tr>
                <Th>{t("assign.create.name")}</Th>
                <Th className="hidden md:table-cell">{t("assign.create.subject")}</Th>
                <Th>{t("assign.detail.status")}</Th>
                <Th>{t("asl.col.due")}</Th>
                <Th className="hidden lg:table-cell">{t("asl.col.work")}</Th>
                <Th className="hidden sm:table-cell" align="right">
                  {t("asl.col.activity")}
                </Th>
              </tr>
            </THead>
            <TBody>
              {shown.map((item) => (
                <Row key={item.id} item={item} locale={locale} />
              ))}
            </TBody>
          </Table>
        )}
        {filtered && items && shown.length > 0 ? (
          <p className="border-t border-border px-3.5 py-2 text-xs text-muted">
            {t("asl.showing", { shown: shown.length, total: inCourse.length })}
          </p>
        ) : null}
      </Panel>
    </div>
  );
}

/** The three open assignments with the nearest due dates, as cards: what to look at first. */
function DueNext({ items, locale }: { items: Assignment[]; locale: string }) {
  const t = useT();
  const next = items
    .filter((item) => item.status !== "done" && item.due_at)
    .sort((a, b) => (a.due_at ?? "").localeCompare(b.due_at ?? ""))
    .slice(0, 3);
  if (next.length === 0) return null;
  return (
    <section aria-labelledby="due-next" className="space-y-2">
      <h2 id="due-next" className="text-[13px] font-semibold text-muted">
        {t("asx.next.title")}
      </h2>
      <ul className="grid gap-3 md:grid-cols-3">
        {next.map((item) => {
          const days = daysLeft(item.due_at) ?? 0;
          const working = item.runs.some((run) => isWorking(run.status));
          return (
            <li key={item.id}>
              <Link
                href={`/assignments/${item.id}`}
                className={`glass spot card-hover group relative block h-full overflow-hidden rounded-3xl p-4 pl-5 ${days < 0 ? "ring-1 ring-danger/40" : ""}`}
              >
                <span aria-hidden className={`absolute inset-y-0 left-0 w-1 ${days < 0 ? "bg-danger" : days <= 2 ? "bg-warning" : "bg-primary"}`} />
                <DueCell dueAt={item.due_at} status={item.status} locale={locale} inline />
                <p className="mt-2 line-clamp-2 font-medium leading-snug group-hover:text-brand">{item.title}</p>
                <p className="mt-1 truncate text-xs text-muted">{item.subject_name ?? t("assign.create.anySubject")}</p>
                <p className="mt-3 flex items-center gap-2 text-xs text-muted">
                  <StatusBadge status={item.status} />
                  {working ? (
                    <span className="flex items-center gap-1 text-info">
                      <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                      {t("asl.work.running")}
                    </span>
                  ) : (
                    <span>{item.word_count > 0 ? t("asl.work.draft", { words: item.word_count }) : t("asl.work.noDraft")}</span>
                  )}
                </p>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Row({ item, locale }: { item: Assignment; locale: string }) {
  const t = useT();
  const working = item.runs.some((run) => isWorking(run.status));
  const ready = item.runs.filter((run) => run.status === "ready").length;
  const work: string[] = [];
  if (item.has_rubric) work.push(t("asl.work.rubric", { points: item.rubric_points }));
  work.push(item.word_count > 0 ? t("asl.work.draft", { words: item.word_count }) : t("asl.work.noDraft"));
  if (item.file_count > 0) work.push(t("asl.work.files", { count: item.file_count }));
  return (
    <Tr className={item.status === "done" ? "text-muted" : undefined}>
      <Td className="max-w-0 min-w-[10rem] sm:min-w-[14rem]">
        <Link href={`/assignments/${item.id}`} className="flex min-w-0 items-start gap-2 hover:text-brand">
          <FileText className="mt-0.5 h-4 w-4 shrink-0 text-faint" aria-hidden />
          <span className="min-w-0">
            <span className="block truncate font-medium" title={item.title}>
              {item.title}
            </span>
            <span className="block truncate text-xs text-muted md:hidden">{item.subject_name ?? t("assign.create.anySubject")}</span>
          </span>
        </Link>
      </Td>
      <Td className="hidden whitespace-nowrap text-muted md:table-cell">
        <span className="block max-w-[11rem] truncate" title={item.subject_name ?? undefined}>
          {item.subject_name ?? "—"}
        </span>
      </Td>
      <Td className="whitespace-nowrap">
        <StatusBadge status={item.status} />
      </Td>
      <Td className="whitespace-nowrap">
        <DueCell dueAt={item.due_at} status={item.status} locale={locale} />
      </Td>
      <Td className="hidden text-xs text-muted lg:table-cell">
        <span className="block">{work.join(" · ")}</span>
        {working ? (
          <span className="mt-0.5 flex items-center gap-1 text-info">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            {t("asl.work.running")}
          </span>
        ) : ready > 0 ? (
          <span className="mt-0.5 block">{t("asl.work.help", { count: ready })}</span>
        ) : null}
      </Td>
      <Td align="right" className="hidden whitespace-nowrap text-xs text-muted sm:table-cell">
        {item.last_activity_at ? relativeTime(item.last_activity_at, locale) : "—"}
      </Td>
    </Tr>
  );
}

function ListSkeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-label={label} className="divide-y divide-border">
      <span className="sr-only">{label}</span>
      {Array.from({ length: 4 }, (_, index) => (
        <div key={index} className="flex items-center gap-4 px-3.5 py-3">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="hidden h-4 w-24 md:block" />
          <Skeleton className="h-4 w-16" />
          <Skeleton className="ml-auto h-4 w-20" />
        </div>
      ))}
    </div>
  );
}

/** Title, course and due date in one row; the brief, files and rubric are added in the workspace
 *  it opens. Files can be dropped on the form (or picked) before the assignment exists: they wait
 *  in a short list and are attached as soon as it is created. */
function QuickCreate({
  subjects,
  course,
  inputRef,
}: {
  subjects: Subject[];
  course: string;
  inputRef: React.RefObject<HTMLInputElement | null>;
}) {
  const t = useT();
  const router = useRouter();
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [subjectId, setSubjectId] = useState(course);
  const [due, setDue] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  useEffect(() => setSubjectId(course), [course]);

  const addFiles = (dropped: File[]) => {
    setFiles((current) => [...current, ...dropped].slice(0, MAX_FILES));
    // A title made from the first file saves typing; it can be changed.
    setTitle((current) => current || titleFromFile(dropped[0]?.name ?? ""));
  };
  const drop = useFileDrop(addFiles, !busy);
  const needsCourse = files.length > 0 && !subjectId;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim() || busy || needsCourse) return;
    setBusy(true);
    try {
      const created = await api<AssignmentDetail>("/assignments", {
        method: "POST",
        body: { title: title.trim(), brief: "", subject_id: subjectId || null, due_at: dueFromInput(due) },
      });
      let failed = 0;
      for (const file of files) {
        try {
          await uploadAssignmentFile(created.id, file);
        } catch {
          failed += 1;
        }
      }
      toast.success(t("asl.created"));
      if (failed > 0) toast.error(t("aw2.hub.someFailed", { count: failed }));
      router.push(`/assignments/${created.id}${files.length > 0 ? "?tab=files" : ""}`);
    } catch (caught) {
      toast.error(workspaceError(caught, t));
      setBusy(false);
    }
  }

  return (
    <form
      {...drop.bind}
      onSubmit={(event) => void submit(event)}
      aria-label={t("assign.create.title")}
      className={`space-y-3 rounded-card border bg-surface px-4 py-3.5 shadow-card ${drop.dragging ? "border-dashed border-primary bg-primary-soft" : "border-border"}`}
    >
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_12rem_9.5rem_auto] sm:items-end">
        <FormRow label={t("assign.create.name")} htmlFor="quick-title">
          <Input
            id="quick-title"
            ref={inputRef}
            value={title}
            maxLength={MAX_TITLE_CHARS}
            placeholder={t("asl.create.placeholder")}
            onChange={(event) => setTitle(event.target.value)}
          />
        </FormRow>
        <FormRow label={t("assign.create.subject")} htmlFor="quick-course">
          <Select id="quick-course" className="w-full" value={subjectId} onChange={(event) => setSubjectId(event.target.value)}>
            <option value="">{t("asl.create.noCourse")}</option>
            {subjects.map((subject) => (
              <option key={subject.id} value={subject.id}>
                {subject.name}
              </option>
            ))}
          </Select>
        </FormRow>
        <FormRow label={`${t("assign.create.due")} (${t("common.optional")})`} htmlFor="quick-due">
          <Input id="quick-due" type="date" value={due} onChange={(event) => setDue(event.target.value)} />
        </FormRow>
        <Button
          type="submit"
          loading={busy}
          disabled={!title.trim() || needsCourse}
          title={!title.trim() ? t("asl.create.needTitle") : needsCourse ? t("aw2.hub.needCourse") : undefined}
        >
          {t("assign.create.submit")}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <input
          ref={picker}
          type="file"
          multiple
          hidden
          accept={ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`).join(",")}
          onChange={(event) => {
            const picked = Array.from(event.target.files ?? []);
            event.target.value = "";
            if (picked.length > 0) addFiles(picked);
          }}
        />
        <Button type="button" variant="secondary" size="sm" disabled={busy || files.length >= MAX_FILES} onClick={() => picker.current?.click()}>
          <Paperclip className="h-3.5 w-3.5" aria-hidden />
          {t("aw2.hub.attach")}
        </Button>
        <span>{files.length === 0 ? t("aw2.hub.dropHint") : t("aw2.hub.staged", { count: files.length })}</span>
      </div>
      {files.length > 0 ? (
        <ul aria-label={t("aw2.hub.staged", { count: files.length })} className="flex flex-wrap gap-1.5">
          {files.map((file, index) => (
            <li key={`${file.name}-${index}`} className="flex max-w-full items-center gap-1.5 rounded-full border border-border bg-surface-2 py-1 pl-2.5 pr-1.5 text-xs">
              <FileText className="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden />
              <span className="max-w-[14rem] truncate">{file.name}</span>
              <button
                type="button"
                disabled={busy}
                onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}
                aria-label={`${t("aw.files.remove")}: ${file.name}`}
                className="rounded p-0.5 text-muted hover:bg-surface-3 hover:text-danger disabled:opacity-40"
              >
                <X className="h-3 w-3" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {needsCourse ? <p className="text-xs text-warning">{t("aw2.hub.needCourse")}</p> : null}
    </form>
  );
}
