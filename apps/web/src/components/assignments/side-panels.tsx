"use client";

import { AlertCircle, CheckCircle2, FileText, Loader2, Plus, Trash2, Upload, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Checklist, InlineText, RunButton, RunState, SourceList } from "@/components/assignments/run-parts";
import type { useAssignmentUploads } from "@/components/assignments/use-uploads";
import { ACCEPTED_EXTENSIONS, MAX_UPLOAD_MB } from "@/components/subjects/model";
import { Dialog } from "@/components/dialog";
import { Meter } from "@/components/dashboard/meter";
import { AnimatedRing } from "@/components/motion/ring";
import { Badge } from "@/components/kit/badge";
import { Button } from "@/components/kit/button";
import { FormRow, Input, Select, Textarea } from "@/components/kit/controls";
import { ConfirmDialog } from "@/components/kit/confirm";
import { Markdown } from "@/components/markdown";
import { Alert } from "@/components/ui";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import {
  MAX_BRIEF_CHARS,
  MAX_CRITERIA,
  MAX_CRITERION_POINTS,
  MAX_FILES,
  breakdownView,
  dueFromInput,
  inputFromDue,
  parseRubricCheck,
  suggestCriteria,
  workspaceError,
  type CriterionDraft,
} from "@/lib/assignments";
import { bcp47, formatBytes, relativeTime } from "@/lib/format";
import type {
  AssignmentDetail,
  AssignmentFile,
  AssignmentRun,
  AssignmentStatus,
  HelpKind,
  Revision,
  RevisionWithBody,
  Rubric,
  Subject,
} from "@/lib/types";

const STATUSES: AssignmentStatus[] = ["todo", "in_progress", "done"];

// ------------------------------------------------------------------------------ brief

export function BriefTab({
  detail,
  subjects,
  onSaved,
}: {
  detail: AssignmentDetail;
  subjects: Subject[];
  onSaved: (detail: AssignmentDetail) => void;
}) {
  const t = useT();
  const [title, setTitle] = useState(detail.title);
  const [subjectId, setSubjectId] = useState(detail.subject_id ?? "");
  const [due, setDue] = useState(inputFromDue(detail.due_at));
  const [status, setStatus] = useState<AssignmentStatus>(detail.status);
  const [brief, setBrief] = useState(detail.brief);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const next = await api<AssignmentDetail>(`/assignments/${detail.id}`, {
        method: "PATCH",
        body: { title: title.trim(), subject_id: subjectId || null, due_at: dueFromInput(due), status, brief },
      });
      onSaved(next);
      setSaved(true);
    } catch (caught) {
      setError(workspaceError(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3 p-3.5">
      <FormRow label={t("assign.create.name")} htmlFor="aw-title">
        <Input id="aw-title" value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} required />
      </FormRow>
      <FormRow label={t("assign.create.subject")} htmlFor="aw-course">
        <Select id="aw-course" className="w-full" value={subjectId} onChange={(e) => setSubjectId(e.target.value)}>
          <option value="">{t("assign.create.anySubject")}</option>
          {subjects.map((subject) => (
            <option key={subject.id} value={subject.id}>
              {subject.name}
            </option>
          ))}
        </Select>
      </FormRow>
      <div className="grid grid-cols-2 gap-3">
        <FormRow label={t("assign.create.due")} htmlFor="aw-due">
          <Input id="aw-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </FormRow>
        <FormRow label={t("assign.detail.status")} htmlFor="aw-status">
          <Select id="aw-status" className="w-full" value={status} onChange={(e) => setStatus(e.target.value as AssignmentStatus)}>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {t(`assign.status.${value}`)}
              </option>
            ))}
          </Select>
        </FormRow>
      </div>
      <FormRow label={t("assign.create.brief")} htmlFor="aw-brief" hint={t("aw.brief.fromFiles")}>
        <Textarea id="aw-brief" rows={9} maxLength={MAX_BRIEF_CHARS} value={brief} onChange={(e) => setBrief(e.target.value)} />
      </FormRow>
      {error ? <Alert>{error}</Alert> : null}
      <div className="flex items-center gap-3">
        <Button type="submit" size="sm" loading={busy} disabled={!title.trim()}>
          {t("assign.detail.save")}
        </Button>
        {saved ? (
          <span role="status" className="text-xs text-muted">
            {t("assign.detail.saved")}
          </span>
        ) : null}
      </div>
    </form>
  );
}

// ------------------------------------------------------------------------------ rubric

export function RubricTab({ detail, onSaved }: { detail: AssignmentDetail; onSaved: (rubric: Rubric | null) => void }) {
  const t = useT();
  const [rows, setRows] = useState<CriterionDraft[]>(
    (detail.rubric?.criteria ?? []).map((c) => ({ id: c.id, title: c.title, points: String(c.points), descriptor: c.descriptor })),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const total = rows.reduce((sum, row) => sum + (Number(row.points) || 0), 0);

  function change(index: number, patch: Partial<CriterionDraft>) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
    setNotice(null);
  }

  function suggest() {
    const found = suggestCriteria(detail.brief);
    if (found.length === 0) setNotice(t("aw.rubric.noneFound"));
    else {
      setRows(found);
      setNotice(null);
    }
  }

  async function save() {
    if (rows.some((row) => !row.title.trim())) {
      setError(t("aw.rubric.invalid"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const saved = await api<Rubric | null>(`/assignments/${detail.id}/rubric`, {
        method: "PUT",
        body: {
          criteria: rows.map((row) => ({
            id: row.id ?? undefined,
            title: row.title.trim(),
            points: Math.max(0, Math.min(MAX_CRITERION_POINTS, Math.round(Number(row.points) || 0))),
            descriptor: row.descriptor.trim(),
          })),
        },
      });
      onSaved(saved);
      setRows((saved?.criteria ?? []).map((c) => ({ id: c.id, title: c.title, points: String(c.points), descriptor: c.descriptor })));
      setNotice(t("aw.rubric.saved"));
    } catch (caught) {
      setError(workspaceError(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 p-3.5">
      <p className="text-xs text-muted">{t("aw.rubric.intro")}</p>
      {rows.length === 0 ? <p className="text-[13px] text-muted">{t("aw.rubric.empty")}</p> : null}
      <ul className="space-y-2">
        {rows.map((row, index) => (
          <li key={row.id ?? `new-${index}`} className="rounded-xl border border-border p-2">
            <div className="flex items-start gap-2">
              <Input
                aria-label={t("aw.rubric.title")}
                placeholder={t("aw.rubric.title")}
                value={row.title}
                maxLength={120}
                onChange={(e) => change(index, { title: e.target.value })}
              />
              <Input
                aria-label={t("aw.rubric.points")}
                type="number"
                min={0}
                max={MAX_CRITERION_POINTS}
                value={row.points}
                onChange={(e) => change(index, { points: e.target.value })}
                className="w-20 shrink-0 tabular"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={t("aw.rubric.remove")}
                onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </Button>
            </div>
            <Textarea
              aria-label={t("aw.rubric.descriptor")}
              placeholder={t("aw.rubric.descriptor")}
              rows={2}
              maxLength={1000}
              value={row.descriptor}
              onChange={(e) => change(index, { descriptor: e.target.value })}
              className="mt-2 text-[13px]"
            />
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={rows.length >= MAX_CRITERIA}
          onClick={() => setRows((current) => [...current, { id: null, title: "", points: "10", descriptor: "" }])}
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          {t("aw.rubric.add")}
        </Button>
        {detail.brief.trim() ? (
          <Button type="button" variant="ghost" size="sm" onClick={suggest}>
            {t("aw.rubric.suggest")}
          </Button>
        ) : null}
        <span className="tabular ml-auto text-xs text-muted">{t("aw.rubric.total", { points: total })}</span>
      </div>
      {error ? <Alert>{error}</Alert> : null}
      {notice ? <p role="status" className="text-xs text-muted">{notice}</p> : null}
      <Button size="sm" onClick={() => void save()} loading={busy}>
        {t("aw.rubric.save")}
      </Button>
    </div>
  );
}

// ------------------------------------------------------------------------------ files

export function FilesTab({
  detail,
  uploads,
  onChanged,
}: {
  detail: AssignmentDetail;
  uploads: ReturnType<typeof useAssignmentUploads>;
  onChanged: () => void;
}) {
  const t = useT();
  const picker = useRef<HTMLInputElement>(null);
  const [removing, setRemoving] = useState<AssignmentFile | null>(null);
  const { queue, upload, dismiss, clearFinished, busy } = uploads;
  const full = detail.files.length >= MAX_FILES;
  const blocked = detail.subject_id === null || full;

  // Files are read in the background; look again while any is still being read.
  const reading = detail.files.some((file) => file.status === "uploaded" || file.status === "processing");
  useEffect(() => {
    if (!reading) return;
    const timer = setInterval(onChanged, 3000);
    return () => clearInterval(timer);
  }, [reading, onChanged]);

  async function remove(file: AssignmentFile) {
    await api(`/assignments/${detail.id}/files/${file.id}`, { method: "DELETE" });
    onChanged();
  }

  const finished = queue.some((item) => item.status === "done" || item.status === "failed");

  return (
    <div className="space-y-3 p-3.5">
      <p className="text-xs text-muted">{t("aw.files.intro")}</p>
      {detail.subject_id === null ? <Alert tone="info">{t("aw.files.needCourse")}</Alert> : null}

      <input
        ref={picker}
        type="file"
        multiple
        hidden
        accept={ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`).join(",")}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          void upload(files);
        }}
      />
      <button
        type="button"
        disabled={blocked || busy}
        onClick={() => picker.current?.click()}
        className="flex w-full flex-col items-center gap-1 rounded-xl border border-dashed border-border-strong px-3 py-5 text-center hover:border-primary hover:bg-primary-soft disabled:opacity-60 disabled:hover:border-border-strong disabled:hover:bg-transparent"
      >
        {busy ? <Loader2 className="h-5 w-5 animate-spin text-muted" aria-hidden /> : <Upload className="h-5 w-5 text-muted" aria-hidden />}
        <span className="text-[13px] font-medium">{busy ? t("aw.files.uploading") : t("aw2.files.drop")}</span>
        <span className="text-xs text-muted">{t("aw2.files.hint", { mb: MAX_UPLOAD_MB, max: MAX_FILES })}</span>
        {full ? <span className="text-xs text-warning">{t("asw.err.tooMany")}</span> : null}
      </button>

      {queue.length > 0 ? (
        <div>
          <ul aria-label={t("aw2.files.queue")} className="divide-y divide-border rounded-xl border border-border">
            {queue.map((item) => (
              <li key={item.id} className="flex items-start gap-2 px-2.5 py-1.5 text-[13px]">
                {item.status === "failed" ? (
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
                ) : item.status === "done" ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
                ) : (
                  <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-muted" aria-hidden />
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{item.name}</span>
                  {item.error ? <span className="block text-xs text-danger">{item.error}</span> : null}
                </span>
                {item.status === "failed" ? (
                  <button type="button" onClick={() => dismiss(item.id)} aria-label={t("common.close")} className="rounded p-0.5 text-muted hover:bg-surface-3">
                    <X className="h-3.5 w-3.5" aria-hidden />
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
          {finished && !busy ? (
            <button type="button" onClick={clearFinished} className="mt-1 text-xs text-muted underline hover:text-ink">
              {t("common.clear")}
            </button>
          ) : null}
        </div>
      ) : null}

      {detail.files.length === 0 ? (
        <p className="text-[13px] text-muted">{t("aw.files.empty")}</p>
      ) : (
        <ul className="divide-y divide-border rounded-xl border border-border">
          {detail.files.map((file) => (
            <li key={file.id} className="flex items-center gap-2 px-2.5 py-2">
              <FileText className="h-4 w-4 shrink-0 text-faint" aria-hidden />
              <div className="min-w-0 flex-1">
                <a
                  href={`/api/v1/materials/${file.id}/download?inline=true`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block truncate text-[13px] font-medium hover:underline"
                >
                  {file.filename}
                </a>
                <p className="tabular text-xs text-muted">{formatBytes(file.size_bytes)}</p>
              </div>
              <Badge tone={file.status === "ready" ? "success" : file.status === "failed" ? "danger" : "neutral"} title={file.error ?? undefined}>
                {t(`materials.status.${file.status}`)}
              </Badge>
              <Button variant="ghost" size="icon" aria-label={`${t("aw.files.remove")}: ${file.filename}`} onClick={() => setRemoving(file)}>
                <Trash2 className="h-4 w-4" aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={removing !== null}
        title={t("aw.files.remove")}
        description={removing ? t("aw.files.removeConfirm", { name: removing.filename }) : undefined}
        confirmLabel={t("aw.files.remove")}
        onClose={() => setRemoving(null)}
        onConfirm={() => (removing ? remove(removing) : undefined)}
      />
    </div>
  );
}

// ------------------------------------------------------------------------------ AI help

const KIND_ORDER: HelpKind[] = ["breakdown", "outline", "feedback"];

export function HelpTab({
  detail,
  runs,
  kinds = KIND_ORDER,
  starting,
  blockedFor,
  onAsk,
}: {
  detail: AssignmentDetail;
  runs: AssignmentRun[];
  /** Which kinds of help this tab offers (AI assistance: breakdown and outline). */
  kinds?: HelpKind[];
  starting: HelpKind | null;
  blockedFor: (kind: HelpKind) => string | null;
  onAsk: (kind: HelpKind) => void;
}) {
  const t = useT();
  const [kind, setKind] = useState<HelpKind>(kinds[0] ?? "breakdown");
  const run = runs.find((item) => item.kind === kind);
  const ready = run?.status === "ready" && run.result ? run : null;
  const [picked, setPicked] = useState<number | null>(null);

  return (
    <div className="space-y-3 p-3.5">
      <p className="text-xs text-muted">{t("assign.detail.helpIntro")}</p>
      <div role="group" aria-label={t("aw.tab.help")} className="flex flex-wrap gap-1.5">
        {kinds.map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={kind === value}
            onClick={() => setKind(value)}
            className={`rounded-xl border px-2.5 py-1 text-xs font-medium ${
              kind === value ? "border-primary bg-primary-soft text-brand" : "border-border-strong text-muted hover:bg-surface-2"
            }`}
          >
            {t(`assign.kind.${value}`)}
          </button>
        ))}
      </div>
      <p className="text-xs text-muted">{t(`assign.kind.${kind}Desc`)}</p>
      <RunButton run={run} starting={starting === kind} blocked={blockedFor(kind)} onAsk={() => onAsk(kind)} label={t("assign.detail.run")} primary />
      {blockedFor(kind) ? <p className="text-xs text-muted">{blockedFor(kind)}</p> : null}
      <RunState run={run} idle={null} />
      {ready ? <RunResult run={ready} rubric={detail.rubric} assignmentId={detail.id} picked={picked} onPick={setPicked} /> : null}
    </div>
  );
}

export function RunResult({
  run,
  rubric,
  assignmentId,
  picked,
  onPick,
}: {
  run: AssignmentRun;
  rubric: Rubric | null;
  assignmentId: string;
  picked: number | null;
  onPick: (n: number) => void;
}) {
  const t = useT();
  const text = run.result ?? "";
  const numbers = run.sources.map((source) => source.n);
  const scores = run.kind === "feedback" && rubric ? parseRubricCheck(text, rubric.criteria) : null;
  const scoreTotal = (scores ?? []).reduce((sum, row) => ({ awarded: sum.awarded + row.awarded, available: sum.available + row.available }), { awarded: 0, available: 0 });
  const breakdown = run.kind === "breakdown" ? breakdownView(text) : null;
  const [full, setFull] = useState(scores === null && breakdown === null);

  return (
    <div className="space-y-3 border-t border-border pt-3">
      {scores && rubric ? (
        <div>
          <div className="flex items-center gap-3">
            <AnimatedRing
              value={scoreTotal.available ? scoreTotal.awarded / scoreTotal.available : 0}
              size={56}
              stroke={5}
              label={t("aw.help.scores")}
            >
              <span className="tabular text-[11px] font-semibold">
                {scoreTotal.available ? Math.round((scoreTotal.awarded / scoreTotal.available) * 100) : 0}%
              </span>
            </AnimatedRing>
            <div className="min-w-0">
              <h4 className="text-[13px] font-semibold">{t("aw.help.scores")}</h4>
              <p className="text-xs text-muted">{t("aw.help.scoresNote")}</p>
            </div>
          </div>
          <ul className="mt-3 divide-y divide-border rounded-2xl border border-border bg-surface/40">
            {scores.map((score) => {
              const criterion = rubric.criteria.find((c) => c.id === score.criterionId);
              return (
                <li key={score.criterionId} className="px-3 py-2.5 text-[13px]">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-medium">{criterion?.title}</span>
                    <span className="tabular shrink-0">
                      {score.awarded} / {score.available}
                    </span>
                  </div>
                  <Meter
                    className="mt-1.5"
                    value={score.available ? score.awarded / score.available : 0}
                    label={criterion?.title ?? t("aw.help.scores")}
                  />
                  {score.note ? <p className="mt-1.5 text-xs text-muted">{score.note}</p> : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {breakdown && breakdown.requirements.length > 0 ? (
        <div>
          <h4 className="mb-1.5 text-[13px] font-semibold">{t("aw.help.requirements")}</h4>
          <Checklist items={breakdown.requirements} storageKey={`mindnest.req.${assignmentId}`} label={t("aw.help.requirements")} />
        </div>
      ) : null}
      {breakdown && breakdown.checklist.length > 0 ? (
        <div>
          <h4 className="mb-1.5 text-[13px] font-semibold">{t("aw.help.beforeSubmit")}</h4>
          <Checklist items={breakdown.checklist} storageKey={`mindnest.submit.${assignmentId}`} label={t("aw.help.beforeSubmit")} />
        </div>
      ) : null}
      {scores || (breakdown && (breakdown.requirements.length > 0 || breakdown.checklist.length > 0)) ? (
        <button type="button" onClick={() => setFull((value) => !value)} aria-expanded={full} className="text-xs font-medium text-brand hover:underline">
          {t("aw.help.more")}
        </button>
      ) : null}
      {full ? (
        <div className="text-[13px]">
          <Markdown text={text} citations={numbers} streaming={false} onCite={onPick} />
        </div>
      ) : null}
      <div>
        <h4 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-faint rtl:tracking-normal">{t("assign.detail.sources")}</h4>
        <SourceList sources={run.sources} picked={picked} />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------ history

export function HistoryTab({
  detail,
  refreshKey,
  onRestored,
}: {
  detail: AssignmentDetail;
  refreshKey: number;
  onRestored: (detail: AssignmentDetail) => void;
}) {
  const t = useT();
  const locale = useLocale();
  const [items, setItems] = useState<Revision[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<RevisionWithBody | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Revision[]>(`/assignments/${detail.id}/revisions`)
      .then(setItems)
      .catch((caught: unknown) => setError(workspaceError(caught, t)));
  }, [detail.id, refreshKey, t]);

  async function view(id: string) {
    try {
      setViewing(await api<RevisionWithBody>(`/assignments/${detail.id}/revisions/${id}`));
    } catch (caught) {
      setError(workspaceError(caught, t));
    }
  }

  async function restore() {
    if (!viewing) return;
    setBusy(true);
    try {
      onRestored(await api<AssignmentDetail>(`/assignments/${detail.id}/revisions/${viewing.id}/restore`, { method: "POST" }));
      setViewing(null);
    } catch (caught) {
      setError(workspaceError(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-3.5">
      {error ? <Alert>{error}</Alert> : null}
      {items === null ? (
        error ? null : <p className="text-[13px] text-muted">{t("common.loading")}</p>
      ) : items.length === 0 ? (
        <p className="text-[13px] text-muted">{t("aw.history.empty")}</p>
      ) : (
        <ul className="divide-y divide-border rounded-xl border border-border">
          {items.map((item) => (
            <li key={item.id} className="flex items-center gap-2 px-2.5 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium">{item.note || t(`aw.history.source.${item.source}`)}</p>
                <p className="tabular text-xs text-muted">
                  {relativeTime(item.updated_at, locale)} · {t("aw.history.words", { count: item.word_count })}
                  {item.note ? ` · ${t(`aw.history.source.${item.source}`)}` : ""}
                </p>
              </div>
              <Button variant="ghost" size="sm" onClick={() => void view(item.id)}>
                {t("aw.history.view")}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <Dialog open={viewing !== null} onClose={() => setViewing(null)} title={viewing ? viewing.note || t(`aw.history.source.${viewing.source}`) : ""} wide>
        {viewing ? (
          <>
            <p className="tabular text-xs text-muted">
              {new Intl.DateTimeFormat(bcp47(locale), { dateStyle: "medium", timeStyle: "short" }).format(new Date(viewing.updated_at))} ·{" "}
              {t("aw.history.words", { count: viewing.word_count })}
            </p>
            <pre className="mt-3 max-h-[50vh] overflow-y-auto whitespace-pre-wrap rounded-xl border border-border bg-surface-2 p-3 text-[13px] leading-6">
              {viewing.body}
            </pre>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setViewing(null)}>
                {t("aw.history.close")}
              </Button>
              <Button loading={busy} onClick={() => void restore()}>
                {t("aw.history.restore")}
              </Button>
            </div>
          </>
        ) : null}
      </Dialog>
    </div>
  );
}

export { InlineText };
