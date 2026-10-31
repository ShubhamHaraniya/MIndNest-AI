import type { MessageKey } from "@/i18n/translate";

import type { MaterialKind, ReportReason, ShareRights } from "./types";

/** Reports needed before a file is hidden (the same number the server uses). */
export const HIDE_AT_REPORTS = 3;
export const REPORT_REASONS: ReportReason[] = ["copyright", "inappropriate", "wrong_content", "other"];
export const MAX_NOTE_CHARS = 300;

export const KIND_KEYS: Record<MaterialKind, MessageKey> = {
  material: "materials.kind.material",
  past_paper: "materials.kind.past_paper",
  note: "materials.kind.note",
  assignment: "materials.kind.assignment",
};

export function formatSize(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export const downloadUrl = (groupId: string, itemId: string) =>
  `/api/v1/groups/${encodeURIComponent(groupId)}/items/${encodeURIComponent(itemId)}/download`;

export const RIGHTS: ShareRights[] = ["own_work", "permitted", "open_licence"];
export const RIGHTS_KEYS: Record<ShareRights, MessageKey> = {
  own_work: "lg.rights.own_work",
  permitted: "lg.rights.permitted",
  open_licence: "lg.rights.open_licence",
};
