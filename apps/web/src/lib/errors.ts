import { ApiError } from "./api";
import type { MessageKey, TFunction } from "@/i18n/translate";

const KNOWN: Record<string, MessageKey> = {
  invalid_credentials: "errors.invalid_credentials",
  email_taken: "errors.email_taken",
  password_unchanged: "errors.password_unchanged",
  rate_limited: "errors.rate_limited",
  invalid_token: "errors.invalid_token",
  validation_error: "errors.validation_error",
  not_found: "errors.not_found",
  network: "errors.network",
  unsupported_type: "errors.unsupported_type",
  file_too_large: "errors.file_too_large",
  empty_file: "errors.empty_file",
  no_provider_key: "errors.no_provider_key",
  key_unreadable: "errors.key_unreadable",
  invalid_dataset: "errors.invalid_dataset",
  dataset_exists: "errors.dataset_exists",
  no_materials: "errors.no_materials",
  empty_dataset: "errors.empty_dataset",
  invalid_case: "errors.invalid_case",
  quiz_not_ready: "errors.quiz_not_ready",
  already_submitted: "errors.already_submitted",
  nothing_due: "errors.nothing_due",
  draft_required: "errors.draft_required",
  brief_required: "errors.brief_required",
  run_in_progress: "errors.run_in_progress",
  plan_task_title: "errors.plan_task_title",
  plan_task_subject: "errors.plan_task_subject",
  gcal_reconnect: "errors.gcal_reconnect",
  gcal_not_connected: "errors.gcal_not_connected",
  calendar_unavailable: "errors.calendar_unavailable",
  approval_expired: "errors.approval_expired",
  google_not_configured: "errors.google_not_configured",
  group_not_found: "errors.group_not_found",
  too_many_groups: "errors.too_many_groups",
  group_full: "errors.group_full",
  owner_only: "errors.owner_only",
  owner_cannot_leave: "errors.owner_cannot_leave",
  rights_required: "errors.rights_required",
  already_shared: "errors.already_shared",
  group_library_full: "errors.group_library_full",
  own_item: "errors.own_item",
  try_again: "errors.try_again",
  forbidden: "errors.forbidden",
  admin_account: "errors.admin_account",
  confirm_rights: "errors.confirm_rights",
  institution_required: "errors.institution_required",
  assignment_not_shareable: "errors.assignment_not_shareable",
  library_full: "errors.library_full",
  already_published: "errors.already_published",
  locked: "errors.locked",
  admin_only: "errors.admin_only",
  not_allowed: "errors.not_allowed",
  not_author: "errors.not_author",
  invalid_email: "errors.invalid_email",
  already_member: "errors.already_member",
  already_invited: "errors.already_invited",
  too_many_invitations: "errors.too_many_invitations",
  invitation_not_found: "errors.invitation_not_found",
  thread_locked: "errors.thread_locked",
  thread_full: "errors.thread_full",
  session_in_past: "errors.session_in_past",
  session_duplicate: "errors.session_duplicate",
  session_closed: "errors.session_closed",
  event_duplicate: "errors.event_duplicate",
  attempt_in_progress: "errors.attempt_in_progress",
  confirmation_required: "errors.confirmation_required",
  google_disabled: "errors.google_disabled",
  google_unverified: "errors.google_unverified",
  invalid_cursor: "errors.invalid_cursor",
  invalid_format: "errors.invalid_format",
  invalid_module: "errors.invalid_module",
  invalid_timezone: "errors.invalid_timezone",
  no_password_set: "errors.no_password_set",
  not_authenticated: "errors.not_authenticated",
  not_failed: "errors.not_failed",
  not_retryable: "errors.not_retryable",
  nothing_missed: "errors.nothing_missed",
  quiz_archived: "errors.quiz_archived",
  subject_required: "errors.subject_required",
  time_up: "errors.time_up",
  too_many_files: "errors.too_many_files",
  group_notes_full: "errors.group_notes_full",
  group_threads_full: "errors.group_threads_full",
  group_sessions_full: "errors.group_sessions_full",
  wrong_password: "errors.wrong_password",
};

/** A message in the user's language for any failure. Unknown errors get the generic one;
 *  server-side wording is never shown, because it is English only. */
export function errorMessage(error: unknown, t: TFunction): string {
  if (error instanceof ApiError) {
    const key = KNOWN[error.code];
    if (key) return t(key);
  }
  return t("errors.generic");
}

const LLM_ERRORS: Record<string, MessageKey> = {
  invalid_key: "chat.llm.invalid_key",
  rate_limited: "chat.llm.rate_limited",
  bad_request: "chat.llm.bad_request",
  provider_unavailable: "chat.llm.provider_unavailable",
  timeout: "chat.llm.timeout",
  blocked: "chat.llm.blocked",
  empty_response: "chat.llm.empty_response",
  provider_error: "chat.llm.provider_error",
  unsafe_output: "chat.llm.unsafe_output",
};

/** A message for a failure reported by an AI provider (a code such as "invalid_key"). */
export function llmErrorText(code: string, t: TFunction): string {
  return t(LLM_ERRORS[code] ?? "chat.llm.internal");
}
