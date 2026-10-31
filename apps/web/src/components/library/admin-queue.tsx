"use client";

import { useCallback, useEffect, useState } from "react";

import { Dialog } from "@/components/dialog";
import { Badge, Button, EmptyState, FormRow, Textarea } from "@/components/kit";
import { Alert } from "@/components/ui";
import { useT } from "@/i18n/client";
import type { MessageKey } from "@/i18n/translate";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { RIGHTS_KEYS } from "@/lib/groups";
import { DOC_TYPE_KEYS, STATUS_KEYS, STATUS_TONES, VISIBILITY_KEYS } from "@/lib/library";
import type { LibraryQueueRow } from "@/lib/types";

type Action = "approve" | "reject" | "takedown";

/** Moderation for the Materials Library: public files waiting for review, files held back by
 *  reports, and anything that has been reported. A moderator sees names and reasons, not file
 *  contents beyond what the owner chose to publish. */
export function LibraryQueue() {
  const t = useT();
  const [rows, setRows] = useState<LibraryQueueRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deciding, setDeciding] = useState<{ row: LibraryQueueRow; action: Action } | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await api<LibraryQueueRow[]>("/admin/library"));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(row: LibraryQueueRow, action: Action, text: string) {
    setBusy(true);
    try {
      await api(`/admin/library/${row.id}/${action}`, { method: "POST", body: { note: text } });
      setDeciding(null);
      setNote("");
      await load();
    } catch (caught) {
      setError(errorMessage(caught, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">{t("admin.library.intro")}</p>
      {error ? <Alert>{error}</Alert> : null}
      {rows === null ? (
        error ? null : <p className="py-6 text-muted">{t("common.loading")}</p>
      ) : rows.length === 0 ? (
        <EmptyState title={t("admin.library.none")} description={t("admin.library.noneBody")} />
      ) : (
        <ul className="space-y-3">
          {rows.map((row) => (
            <li key={row.id} className="rounded-card border border-border bg-surface p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="break-words font-medium">{row.title}</p>
                  <p className="mt-0.5 break-words text-xs text-muted">
                    {row.filename} · {t(DOC_TYPE_KEYS[row.doc_type])} · {t("admin.reports.by_name", { name: row.owner_name })}
                    {row.institution ? ` · ${row.institution}` : ""}
                    {row.author ? ` · ${t("ml.by", { author: row.author })}` : ""}
                  </p>
                  <p className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                    <Badge tone={STATUS_TONES[row.status]}>{t(STATUS_KEYS[row.status])}</Badge>
                    <Badge>{t(VISIBILITY_KEYS[row.visibility])}</Badge>
                    <Badge>{t(RIGHTS_KEYS[row.rights])}</Badge>
                    {row.reports > 0 ? <span className="text-muted">{t("lib.file.reports", { count: row.reports })}</span> : null}
                    {row.reasons.map((reason) => (
                      <span key={reason} className="rounded-full bg-surface-3 px-2 py-0.5 text-muted">
                        {t(`lib.report.reason.${reason}` as MessageKey)}
                      </span>
                    ))}
                    {row.imports > 0 ? <span className="text-muted">{t("admin.library.imports", { count: row.imports })}</span> : null}
                  </p>
                  {row.notes.length > 0 ? (
                    <ul className="mt-2 list-inside list-disc text-sm text-muted">
                      {row.notes.map((text, index) => (
                        <li key={index} className="break-words">
                          {text}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
                <div className="flex flex-wrap gap-2">
                  {(row.status !== "taken_down" && row.status !== "published") || row.reports > 0 ? (
                    <Button variant="secondary" size="sm" onClick={() => void decide(row, "approve", "")}>
                      {row.status === "pending_review" ? t("admin.library.approve") : t("admin.library.keep")}
                    </Button>
                  ) : null}
                  {row.status !== "rejected" && row.status !== "taken_down" ? (
                    <Button variant="secondary" size="sm" onClick={() => setDeciding({ row, action: "reject" })}>
                      {t("admin.library.reject")}
                    </Button>
                  ) : null}
                  {row.status !== "taken_down" ? (
                    <Button variant="danger" size="sm" onClick={() => setDeciding({ row, action: "takedown" })}>
                      {t("admin.library.takedown")}
                    </Button>
                  ) : null}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      <Dialog
        open={deciding !== null}
        onClose={() => setDeciding(null)}
        title={deciding?.action === "takedown" ? t("admin.library.takedownTitle") : t("admin.library.rejectTitle")}
      >
        {deciding ? (
          <div className="space-y-4">
            <p className="text-sm text-muted">
              {deciding.action === "takedown"
                ? t("admin.library.takedownBody", { count: deciding.row.imports })
                : t("admin.library.rejectBody")}
            </p>
            <FormRow label={t("admin.library.note")} htmlFor="admin-lib-note" hint={t("admin.library.noteHint")}>
              <Textarea id="admin-lib-note" rows={3} maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} />
            </FormRow>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setDeciding(null)}>
                {t("common.cancel")}
              </Button>
              <Button
                variant={deciding.action === "takedown" ? "danger" : "primary"}
                loading={busy}
                onClick={() => void decide(deciding.row, deciding.action, note.trim())}
              >
                {deciding.action === "takedown" ? t("admin.library.takedown") : t("admin.library.reject")}
              </Button>
            </div>
          </div>
        ) : null}
      </Dialog>
    </div>
  );
}
