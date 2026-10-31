/** Small rules for the chat screens that need no React: what a conversation may search, the
 *  blocks hidden from a half-written answer, and the messages for chat-specific errors. */

import type { MessageKey, TFunction } from "@/i18n/translate";
import { ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Conversation, FeedbackReason } from "@/lib/types";

export type ScopeKind = "all" | "subject" | "materials";

/** What the student chose the chat may search. */
export type ScopeValue = { kind: ScopeKind; subjectId: string; materialIds: string[] };

export const ALL_COURSES: ScopeValue = { kind: "all", subjectId: "", materialIds: [] };

export function scopeOf(conversation: Pick<Conversation, "scope" | "subject_id" | "material_ids">): ScopeValue {
  if (conversation.scope === "materials") {
    return { kind: "materials", subjectId: "", materialIds: conversation.material_ids ?? [] };
  }
  if (conversation.scope === "subject" || (conversation.scope === undefined && conversation.subject_id)) {
    return { kind: "subject", subjectId: conversation.subject_id ?? "", materialIds: [] };
  }
  return ALL_COURSES;
}

export function courseScope(subjectId: string | null): ScopeValue {
  return subjectId ? { kind: "subject", subjectId, materialIds: [] } : ALL_COURSES;
}

/** The request body that sets the scope (the server reads `subject_id` / `material_ids`). */
export function scopeBody(scope: ScopeValue): { scope: ScopeKind; subject_id?: string; material_ids?: string[] } {
  if (scope.kind === "subject") return { scope: "subject", subject_id: scope.subjectId };
  if (scope.kind === "materials") return { scope: "materials", material_ids: scope.materialIds };
  return { scope: "all" };
}

export const MAX_SCOPE_FILES = 50;
/** How many files one conversation can hold (the server enforces the same number). */
export const MAX_ATTACHMENTS = 5;

export const FEEDBACK_REASONS: { value: FeedbackReason; key: MessageKey }[] = [
  { value: "incorrect", key: "chx.reason.incorrect" },
  { value: "not_in_materials", key: "chx.reason.not_in_materials" },
  { value: "unclear", key: "chx.reason.unclear" },
  { value: "too_long", key: "chx.reason.too_long" },
  { value: "unsafe", key: "chx.reason.unsafe" },
  { value: "other", key: "chx.reason.other" },
];

const CHAT_ERRORS: Record<string, MessageKey> = {
  too_many_attachments: "chx.err.too_many_attachments",
  type_mismatch: "chx.err.type_mismatch",
  unsupported_type: "chx.err.unsupported_type",
  file_too_large: "chx.err.file_too_large",
  empty_file: "chx.err.empty_file",
  not_last_answer: "chx.err.not_last_answer",
  no_question: "chx.err.not_last_answer",
  invalid_scope: "chx.err.scope",
  scope_needs_subject: "chx.err.scope",
  scope_needs_materials: "chx.err.scope",
  too_many_materials: "chx.err.too_many_materials",
};

/** A message for a failed chat request, including the errors only the chat can raise. */
export function chatError(error: unknown, t: TFunction): string {
  if (error instanceof ApiError && CHAT_ERRORS[error.code]) return t(CHAT_ERRORS[error.code]);
  return errorMessage(error, t);
}

/** Why an attached file could not be read, in the student's language. */
export function attachmentFailure(code: string | null): MessageKey {
  switch (code) {
    case "encrypted_file":
      return "chx.fail.encrypted_file";
    case "no_text":
      return "chx.fail.no_text";
    case "ocr_unavailable":
      return "chx.fail.ocr_unavailable";
    case "too_many_scanned_pages":
      return "chx.fail.too_many_scanned_pages";
    case "unreadable_file":
      return "chx.fail.unreadable_file";
    case "queue_unavailable":
      return "chx.fail.queue_unavailable";
    default:
      return "chx.fail.generic";
  }
}

const FOLLOWUPS_FENCE = "mindnest-followups";
const CHOICES_FENCE = "mindnest-choices";
const TAIL_BLOCK = new RegExp(`\\n*\`\`\`(?:${FOLLOWUPS_FENCE}|${CHOICES_FENCE})[ \\t]*\\n[\\s\\S]*?\\n?\`\`\`[ \\t]*`, "g");
const TAIL_OPEN = new RegExp(`\\n*\`\`\`(?:${FOLLOWUPS_FENCE}|${CHOICES_FENCE})[ \\t]*(?:\\n[\\s\\S]*)?$`);

/** The text of an answer that is still being written, without the follow-up / choice block at its
 *  end (also when only the first characters of the opening fence have arrived). The server cuts
 *  the saved answer the same way. */
export function stripPartialTail(text: string): string {
  const cut = text.replace(TAIL_BLOCK, "").replace(TAIL_OPEN, "");
  const last = cut.slice(cut.lastIndexOf("\n") + 1);
  if (last.length > 3 && [FOLLOWUPS_FENCE, CHOICES_FENCE].some((name) => `\`\`\`${name}`.startsWith(last))) {
    return cut.slice(0, cut.length - last.length).trimEnd();
  }
  return cut;
}

/** Whether a stored size is shown as KB or MB. */
export function fileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export const ATTACH_ACCEPT = ".pdf,.docx,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg";
