import type { MessageKey } from "@/i18n/translate";

import type { LibraryDocType, LibraryScope, LibraryStatus, LibraryVisibility } from "./types";

export const SCOPES: LibraryScope[] = ["college", "others", "global", "mine"];
export const SCOPE_KEYS: Record<LibraryScope, MessageKey> = {
  college: "ml.scope.college",
  others: "ml.scope.others",
  global: "ml.scope.global",
  mine: "ml.scope.mine",
};
export const SCOPE_HELP_KEYS: Record<LibraryScope, MessageKey> = {
  college: "ml.scope.college.help",
  others: "ml.scope.others.help",
  global: "ml.scope.global.help",
  mine: "ml.scope.mine.help",
};

export const DOC_TYPES: LibraryDocType[] = ["notes", "past_paper", "textbook", "slides", "reference", "other"];
export const DOC_TYPE_KEYS: Record<LibraryDocType, MessageKey> = {
  notes: "ml.type.notes",
  past_paper: "ml.type.past_paper",
  textbook: "ml.type.textbook",
  slides: "ml.type.slides",
  reference: "ml.type.reference",
  other: "ml.type.other",
};

export const VISIBILITIES: LibraryVisibility[] = ["private", "institution", "public"];
export const VISIBILITY_KEYS: Record<LibraryVisibility, MessageKey> = {
  private: "ml.vis.private",
  institution: "ml.vis.institution",
  public: "ml.vis.public",
};
export const VISIBILITY_HELP_KEYS: Record<LibraryVisibility, MessageKey> = {
  private: "ml.vis.private.help",
  institution: "ml.vis.institution.help",
  public: "ml.vis.public.help",
};

export const STATUS_KEYS: Record<LibraryStatus, MessageKey> = {
  draft: "ml.status.draft",
  pending_review: "ml.status.pending_review",
  published: "ml.status.published",
  rejected: "ml.status.rejected",
  held: "ml.status.held",
  taken_down: "ml.status.taken_down",
};

export const STATUS_TONES: Record<LibraryStatus, "neutral" | "info" | "success" | "warning" | "danger"> = {
  draft: "neutral",
  pending_review: "info",
  published: "success",
  rejected: "warning",
  held: "warning",
  taken_down: "danger",
};

export const PAGE_SIZE = 30;

/** A file the preview pane may frame, or a download link. */
export const fileUrl = (id: string, inline = false) =>
  `/api/v1/library/${encodeURIComponent(id)}/file${inline ? "?inline=true" : ""}`;
