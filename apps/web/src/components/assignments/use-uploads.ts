"use client";

import { useCallback, useRef, useState } from "react";

import { useT } from "@/i18n/client";
import { ApiError, uploadAssignmentFile } from "@/lib/api";
import { MAX_FILES, workspaceError } from "@/lib/assignments";

export type UploadItem = { id: number; name: string; status: "waiting" | "uploading" | "done" | "failed"; error: string | null };

/** Uploads files onto an assignment one after another and keeps a visible queue, so a drop of
 *  several files shows what happened to each. A problem that would hit every file (no course, too
 *  many files) fails the rest at once with the same reason. */
export function useAssignmentUploads({
  assignmentId,
  attached,
  hasCourse,
  onUploaded,
}: {
  assignmentId: string;
  /** How many files the assignment already has. */
  attached: number;
  hasCourse: boolean;
  onUploaded: () => void;
}) {
  const t = useT();
  const [queue, setQueue] = useState<UploadItem[]>([]);
  const next = useRef(1);
  const running = useRef(false);

  const patch = useCallback((id: number, change: Partial<UploadItem>) => {
    setQueue((items) => items.map((item) => (item.id === id ? { ...item, ...change } : item)));
  }, []);

  const upload = useCallback(
    async (files: File[]) => {
      if (files.length === 0 || running.current) return;
      const items: UploadItem[] = files.map((file) => ({ id: next.current++, name: file.name, status: "waiting", error: null }));
      setQueue((previous) => [...previous.filter((item) => item.status !== "done"), ...items]);

      if (!hasCourse) {
        for (const item of items) patch(item.id, { status: "failed", error: t("asw.err.subject") });
        return;
      }
      running.current = true;
      let room = MAX_FILES - attached;
      let stop: string | null = null;
      try {
        for (const [index, file] of files.entries()) {
          const item = items[index];
          if (stop !== null) {
            patch(item.id, { status: "failed", error: stop });
            continue;
          }
          if (room <= 0) {
            stop = t("asw.err.tooMany");
            patch(item.id, { status: "failed", error: stop });
            continue;
          }
          patch(item.id, { status: "uploading" });
          try {
            await uploadAssignmentFile(assignmentId, file);
            room -= 1;
            patch(item.id, { status: "done" });
          } catch (caught) {
            const message = workspaceError(caught, t);
            if (caught instanceof ApiError && (caught.code === "subject_required" || caught.code === "too_many_files")) stop = message;
            patch(item.id, { status: "failed", error: message });
          }
        }
      } finally {
        running.current = false;
        onUploaded();
      }
    },
    [assignmentId, attached, hasCourse, onUploaded, patch, t],
  );

  const dismiss = useCallback((id: number) => setQueue((items) => items.filter((item) => item.id !== id)), []);
  const clearFinished = useCallback(() => setQueue((items) => items.filter((item) => item.status === "uploading" || item.status === "waiting")), []);
  const busy = queue.some((item) => item.status === "uploading" || item.status === "waiting");

  return { queue, upload, dismiss, clearFinished, busy };
}
