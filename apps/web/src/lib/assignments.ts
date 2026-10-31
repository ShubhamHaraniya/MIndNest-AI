import type { TFunction } from "@/i18n/translate";

import { ApiError } from "./api";
import { errorMessage, llmErrorText } from "./errors";
import type { HelpKind, RubricCriterion, RunStatus } from "./types";

export const HELP_KINDS: HelpKind[] = ["breakdown", "outline", "feedback"];
export const MAX_BRIEF_CHARS = 8000;
export const MAX_DRAFT_CHARS = 20000;
export const MAX_TITLE_CHARS = 120;

export function isWorking(status: RunStatus): boolean {
  return status === "queued" || status === "running";
}

export type DueState = "none" | "overdue" | "soon" | "later";

const DAY_MS = 86_400_000;

/** How urgent a due date is. A finished assignment is never overdue. */
export function dueState(dueAt: string | null, done: boolean, now: number = Date.now()): DueState {
  if (!dueAt) return "none";
  const left = new Date(dueAt).getTime() - now;
  if (left < 0) return done ? "later" : "overdue";
  return left <= 3 * DAY_MS ? "soon" : "later";
}

/** "2026-11-05" (a date picker value) to the end of that day in the student's own time zone,
 *  as an ISO string the API accepts. Empty means no due date. */
export function dueFromInput(value: string): string | null {
  if (!value) return null;
  const date = new Date(`${value}T23:59:00`);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** The reverse: an ISO time to the local calendar day a date picker shows. */
export function inputFromDue(dueAt: string | null): string {
  if (!dueAt) return "";
  const date = new Date(dueAt);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Why a piece of help could not be written, in the student's language. */
export function failureText(code: string | null, t: TFunction): string {
  if (code === "no_provider_key") return t("errors.no_provider_key");
  if (code === "key_unreadable") return t("errors.key_unreadable");
  return llmErrorText(code ?? "", t);
}

// ------------------------------------------------------------------------------ deadlines

export type DueTone = "neutral" | "warning" | "danger";

/** Whole calendar days from today to the due date in the student's own time zone
 *  (negative once it has passed). Null when there is no due date. */
export function daysLeft(dueAt: string | null, now: Date = new Date()): number | null {
  if (!dueAt) return null;
  const due = new Date(dueAt);
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  return Math.round((startOf(due) - startOf(now)) / DAY_MS);
}

export function dueTone(days: number | null, done: boolean): DueTone {
  if (days === null || done) return "neutral";
  if (days < 0) return "danger";
  return days <= 2 ? "warning" : "neutral";
}

export function countWords(text: string): number {
  const trimmed = text.trim();
  return trimmed === "" ? 0 : trimmed.split(/\s+/).length;
}

/** The error for an assignment action: the two new codes here, everything else as usual. */
export function workspaceError(error: unknown, t: TFunction): string {
  if (error instanceof ApiError) {
    if (error.code === "subject_required") return t("asw.err.subject");
    if (error.code === "too_many_files") return t("asw.err.tooMany");
  }
  return errorMessage(error, t);
}

// ------------------------------------------------------------------------------ AI answers

export type AnswerSection = { heading: string; body: string };

/** The answer split at its `## ` headings. Text before the first heading is `intro`. */
export function splitSections(markdown: string): { intro: string; sections: AnswerSection[] } {
  const sections: AnswerSection[] = [];
  const intro: string[] = [];
  let current: { heading: string; lines: string[] } | null = null;
  let fenced = false;
  for (const line of markdown.split("\n")) {
    if (line.trimStart().startsWith("```")) fenced = !fenced;
    const heading = !fenced ? /^##\s+(.+?)\s*#*\s*$/.exec(line) : null;
    if (heading) {
      if (current) sections.push({ heading: current.heading, body: current.lines.join("\n").trim() });
      current = { heading: heading[1], lines: [] };
    } else if (current) current.lines.push(line);
    else intro.push(line);
  }
  if (current) sections.push({ heading: current.heading, body: current.lines.join("\n").trim() });
  return { intro: intro.join("\n").trim(), sections };
}

/** The bullet or numbered items of a block of Markdown, each on one line. */
export function listItems(body: string): string[] {
  const items: string[] = [];
  for (const line of body.split("\n")) {
    const match = /^\s*(?:[-*•]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.+)$/.exec(line);
    if (match) items.push(match[1].trim());
    else if (/^\s{2,}\S/.test(line) && items.length > 0) items[items.length - 1] += ` ${line.trim()}`;
  }
  return items;
}

export type BreakdownView = {
  requirements: string[];
  /** Text of the "what it asks" section that is not a list (for example, what the brief leaves unclear). */
  requirementsNote: string;
  checklist: string[];
  rest: AnswerSection[];
};

/** The breakdown, organised: the requirements as a list to tick off, the "before you submit"
 *  checklist, and the other sections as reading. The headings are matched by name (English) and,
 *  failing that, by position, because the model answers in the student's language. */
export function breakdownView(markdown: string): BreakdownView {
  const { intro, sections } = splitSections(markdown);
  const byName = (pattern: RegExp) => sections.findIndex((section) => pattern.test(section.heading));
  let askIndex = byName(/what it asks|requirement/i);
  let submitIndex = byName(/before you submit|checklist/i);
  if (askIndex < 0 && sections.length >= 4) askIndex = 0;
  if (submitIndex < 0 && sections.length >= 4) submitIndex = sections.length - 1;
  const ask = askIndex >= 0 ? sections[askIndex] : null;
  const requirements = ask ? listItems(ask.body) : [];
  const requirementsNote = ask
    ? ask.body
        .split("\n")
        .filter((line) => !/^\s*(?:[-*•]|\d+[.)])\s+/.test(line) && !/^\s{2,}\S/.test(line))
        .join(" ")
        .trim()
    : "";
  const checklist = submitIndex >= 0 ? listItems(sections[submitIndex].body) : [];
  const rest = sections.filter((_, index) => index !== askIndex && index !== submitIndex);
  if (!ask && intro) rest.unshift({ heading: "", body: intro });
  return { requirements, requirementsNote, checklist, rest };
}

export type CriterionScore = { criterionId: string; awarded: number; available: number; note: string };

const SCORE_LINE =
  /^\s*(?:[-*•]|\d+[.)])?\s*\*{0,2}\s*(.+?)\s*\*{0,2}\s*[—–-]\s*(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)(?:\s*(?:points?|pts?|marks?))?\s*(?:[—–:-]\s*(.*))?$/;

function normalise(title: string): string {
  return title.replace(/[*_`]/g, "").replace(/\s+/g, " ").trim().toLowerCase();
}

/** The per-criterion estimates in a feedback answer written with a rubric ("**Title** — 4 / 6 —
 *  reason"), matched to the rubric by title. The rubric's own points are the maximum. Null when
 *  nothing could be matched, so the page then shows the answer as written. */
export function parseRubricCheck(markdown: string, criteria: RubricCriterion[]): CriterionScore[] | null {
  const found = new Map<string, CriterionScore>();
  for (const line of markdown.split("\n")) {
    const match = SCORE_LINE.exec(line);
    if (!match) continue;
    const title = normalise(match[1]);
    const criterion = criteria.find((c) => normalise(c.title) === title) ?? criteria.find((c) => title.includes(normalise(c.title)) || normalise(c.title).includes(title));
    if (!criterion || found.has(criterion.id)) continue;
    const awarded = Math.max(0, Math.min(Number(match[2]), criterion.points));
    found.set(criterion.id, { criterionId: criterion.id, awarded, available: criterion.points, note: (match[4] ?? "").replace(/\*+/g, "").trim() });
  }
  if (found.size === 0) return null;
  return criteria.flatMap((c) => (found.has(c.id) ? [found.get(c.id) as CriterionScore] : []));
}

// ------------------------------------------------------------------------------ rubric

export const MAX_CRITERIA = 20;
export const MAX_CRITERION_POINTS = 1000;
export const MAX_FILES = 10;

export type CriterionDraft = { id: string | null; title: string; points: string; descriptor: string };

const CRITERION_AFTER = /^(.{3,100}?)\s*[:\-–—(]\s*(\d{1,3})\s*(?:%|marks?|points?|pts?)\)?\.?\s*(.*)$/i;
const CRITERION_BEFORE = /^(\d{1,3})\s*(?:%|marks?|points?|pts?)\s*[:\-–—]\s*(.{3,100})$/i;

/** Marking criteria written in the brief ("Analysis – 30 marks", "Clarity (20%)", "10 marks: Method"),
 *  offered as a starting point. Lines that look like totals are skipped. */
export function suggestCriteria(text: string): CriterionDraft[] {
  const found: CriterionDraft[] = [];
  const seen = new Set<string>();
  for (const raw of text.split("\n")) {
    const line = raw.replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "").replace(/\*\*/g, "").trim();
    let title = "";
    let points = "";
    let descriptor = "";
    const after = CRITERION_AFTER.exec(line);
    const before = CRITERION_BEFORE.exec(line);
    if (after) {
      title = after[1];
      points = after[2];
      descriptor = after[3].replace(/^[:\-–—,.\s]+/, "");
    } else if (before) {
      points = before[1];
      title = before[2];
    } else continue;
    title = title.replace(/[:\-–—(\s]+$/, "").trim();
    if (title.length < 3 || /\btotal\b|\bout of\b/i.test(title) || Number(points) <= 0) continue;
    const key = normalise(title);
    if (seen.has(key)) continue;
    seen.add(key);
    found.push({ id: null, title: title.slice(0, 120), points, descriptor: descriptor.slice(0, 1000) });
    if (found.length >= MAX_CRITERIA) break;
  }
  return found;
}

// ------------------------------------------------------------------------------ overview

export type ReadinessKey = "instructions" | "files" | "rubric" | "draft" | "feedback" | "version";
export type ReadinessItem = { key: ReadinessKey; done: boolean; detail: Record<string, number> };

/** What has been set up on an assignment, from facts the page already has. */
export function readiness(detail: {
  has_brief: boolean;
  files: { status: string }[];
  rubric: { total: number } | null;
  draft: string;
  latest_runs: { kind: string; status: string }[];
  revision_count: number;
}): ReadinessItem[] {
  const words = countWords(detail.draft);
  const read = detail.files.filter((f) => f.status === "ready").length;
  const feedback = detail.latest_runs.some((r) => r.kind === "feedback" && r.status === "ready");
  return [
    { key: "instructions", done: detail.has_brief || read > 0, detail: { files: read } },
    { key: "files", done: detail.files.length > 0, detail: { count: detail.files.length, ready: read } },
    { key: "rubric", done: detail.rubric !== null, detail: { points: detail.rubric?.total ?? 0 } },
    { key: "draft", done: words > 0, detail: { words } },
    { key: "feedback", done: feedback, detail: {} },
    { key: "version", done: detail.revision_count > 0, detail: { count: detail.revision_count } },
  ];
}

export type NextStep = "instructions" | "draft" | "feedback" | "version" | "finish";

/** The one thing to do next, in order: say what is asked, start writing, get feedback, keep a
 *  version, then finish. Never invented: it only looks at what exists. */
export function nextStep(items: ReadinessItem[], status: string): NextStep | null {
  if (status === "done") return null;
  const done = (key: ReadinessKey) => items.find((i) => i.key === key)?.done ?? false;
  if (!done("instructions")) return "instructions";
  if (!done("draft")) return "draft";
  if (!done("feedback")) return "feedback";
  if (!done("version")) return "version";
  return "finish";
}

/** Dragging files over the page: true while files (not text or a link) are being dragged. */
export function hasFiles(event: { dataTransfer: DataTransfer | null }): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}

/** A title for an assignment made from a dropped file: its name without the extension. */
export function titleFromFile(name: string): string {
  const base = name.replace(/\.[^.]+$/, "").replace(/[_]+/g, " ").replace(/\s+/g, " ").trim();
  return base.slice(0, MAX_TITLE_CHARS);
}
