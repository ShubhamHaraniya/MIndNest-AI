import type { MessageKey } from "@/i18n/translate";
import type { Material, MaterialKind } from "@/lib/types";

/** The shapes returned by the course routes (`/courses`, `/subjects/{id}/overview|progress`). */

export type CourseFigures = {
  id: string;
  name: string;
  course_code: string | null;
  semester: string | null;
  description: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  documents: number;
  documents_ready: number;
  documents_working: number;
  documents_failed: number;
  past_papers: number;
  notes: number;
  quizzes: number;
  quiz_attempts: number;
  quiz_average: number | null;
  chats: number;
  next_exam_title: string | null;
  next_exam_on: string | null;
  next_exam_days: number | null;
  last_activity_at: string | null;
};

export type CoursePage = { items: CourseFigures[]; total: number };

export type ExamBrief = { id: string; title: string; exam_on: string; days_left: number };
export type CourseOverview = { course: CourseFigures; exams: ExamBrief[] };

export type ProgressSummary = {
  answers: number;
  accuracy: number | null;
  attempts: number;
  last_practised_at: string | null;
  weak_documents: number;
};

export type ModuleProgress = {
  module: string | null;
  documents: number;
  documents_ready: number;
  past_papers: number;
  notes: number;
  answers: number;
  accuracy: number | null;
  last_practised_at: string | null;
  weak: boolean;
};

export type DocumentProgress = {
  material_id: string | null;
  filename: string;
  kind: MaterialKind | null;
  module: string | null;
  status: string | null;
  answers: number;
  accuracy: number | null;
  last_practised_at: string | null;
  weak: boolean;
};

export type CourseProgress = {
  summary: ProgressSummary;
  modules: ModuleProgress[];
  documents: DocumentProgress[];
};

export type QuizBrief = {
  id: string;
  title: string;
  source: string;
  subject_id: string | null;
  language: string;
  status: string;
  error: string | null;
  question_count: number;
  created_at: string;
  attempts: number;
  last_attempt: {
    id: string;
    status: string;
    points: number;
    total: number;
    unscored: number;
    percent: number | null;
    finished_at: string | null;
  } | null;
};

export const TAB_IDS = ["overview", "modules", "documents", "notes", "papers", "quizzes", "assignments", "analytics"] as const;
export type TabId = (typeof TAB_IDS)[number];

export function parseTab(value: string | null): TabId {
  if (value === "progress") return "analytics"; // the old name of the analytics tab
  return (TAB_IDS as readonly string[]).includes(value ?? "") ? (value as TabId) : "overview";
}

/** Figures for the analytics tab and the "recommended next" list (`/subjects/{id}/analytics`). */
export type AttemptPoint = {
  attempt_id: string;
  quiz_id: string;
  quiz_title: string;
  finished_at: string;
  points: number;
  total: number;
  percent: number;
};
export type TypeAccuracy = { qtype: string; answers: number; accuracy: number | null };
export type WeekPoint = { week_start: string; attempts: number; answers: number; accuracy: number | null };
export type Recommendation = {
  kind: "deadline" | "revision_due" | "weak_topic" | "retry_failed" | "first_quiz" | "upload_first";
  priority: number;
  ref_id: string | null;
  label: string | null;
  params: Record<string, number | string>;
};
export type CourseAnalytics = {
  attempts: AttemptPoint[];
  trend: "improving" | "steady" | "declining" | null;
  by_type: TypeAccuracy[];
  weeks: WeekPoint[];
  coverage: {
    documents: number;
    documents_ready: number;
    documents_practised: number;
    practised_share: number | null;
    modules_with_files: number;
    modules_practised: number;
  };
  progress: number | null;
  progress_parts: { key: "materials" | "quizzes" | "tasks"; value: number | null; weight: number }[];
  assignments: {
    todo: number;
    in_progress: number;
    done: number;
    overdue: number;
    next_due_at: string | null;
    next_due_title: string | null;
  };
  revision: { cards: number; due: number };
  recommendations: Recommendation[];
};

/** The module filter value that means "files with no module". */
export const NO_MODULE = "__none__";

export const MAX_UPLOAD_MB = 50;
export const ACCEPTED_EXTENSIONS = ["pdf", "pptx", "docx", "txt", "md", "png", "jpg", "jpeg", "webp"];
export const POLL_MS = 2000;
/** A file still "waiting to start" after this long is offered a retry: the worker may have missed it. */
export const STALE_UPLOAD_MS = 60_000;

export const KIND_KEYS: Record<MaterialKind, MessageKey> = {
  material: "materials.kind.material",
  past_paper: "sj.kind.past_paper",
  note: "sj.kind.note",
  assignment: "sj.kind.assignment",
};
export const KINDS: MaterialKind[] = ["material", "past_paper", "note", "assignment"];

export const STAGE_KEYS: Record<string, MessageKey> = {
  validate: "materials.stage.validate",
  parse: "materials.stage.parse",
  ocr: "materials.stage.ocr",
  chunk: "materials.stage.chunk",
  embed: "materials.stage.embed",
};
/** Order of the ingestion stages, for a "step 3 of 5" style progress bar. */
export const STAGE_ORDER = ["validate", "parse", "ocr", "chunk", "embed"];

export const INGEST_ERROR_KEYS: Record<string, MessageKey> = {
  no_text: "materials.error.no_text",
  unreadable_file: "materials.error.unreadable_file",
  encrypted_file: "materials.error.encrypted_file",
  ocr_unavailable: "materials.error.ocr_unavailable",
  too_many_scanned_pages: "materials.error.too_many_scanned_pages",
  too_large: "materials.error.too_large",
  embedding_unreachable: "materials.error.embedding_unreachable",
  embedding_failed: "materials.error.embedding_failed",
  embedding_dimension_mismatch: "materials.error.embedding_dimension_mismatch",
  unsupported_type: "materials.error.unsupported_type",
};

/** Types the browser can show in a frame (the server only serves these inline). */
export const FRAME_TYPES = new Set(["application/pdf", "image/png", "image/jpeg", "text/plain"]);
const MARKDOWN_TYPES = new Set(["text/markdown", "text/x-markdown"]);

export type PreviewMode = "pdf" | "image" | "text" | "markdown" | "none";

export function previewMode(material: Material): PreviewMode {
  const mime = material.mime_type ?? "";
  const name = material.filename.toLowerCase();
  if (mime === "application/pdf") return "pdf";
  if (mime.startsWith("image/") && FRAME_TYPES.has(mime)) return "image";
  if (MARKDOWN_TYPES.has(mime) || name.endsWith(".md")) return "markdown";
  if (mime === "text/plain") return "text";
  return "none";
}

export const isWorking = (m: Pick<Material, "status">): boolean => m.status === "uploaded" || m.status === "processing";

export function isStale(m: Pick<Material, "status" | "created_at">, now = Date.now()): boolean {
  return m.status === "uploaded" && now - Date.parse(m.created_at) > STALE_UPLOAD_MS;
}

export function fileExtension(name: string): string {
  return name.includes(".") ? (name.split(".").pop() ?? "").toLowerCase() : "";
}

export const inlineUrl = (id: string): string => `/api/v1/materials/${id}/download?inline=true`;
export const downloadUrl = (id: string): string => `/api/v1/materials/${id}/download`;

/** "Unit 2" before "Unit 10". Used for module lists the server did not already order. */
export function naturalCompare(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

/** A file name for a written note: the title, with characters that are not allowed in a name removed. */
export function noteFilename(title: string): string {
  const cleaned = title
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^\.+/, "")
    .slice(0, 120)
    .trim();
  return `${cleaned || "note"}.md`;
}
