"use client";

import { ChevronDown } from "lucide-react";
import { useEffect, useState } from "react";

import { RunButton, RunState } from "@/components/assignments/run-parts";
import { RunResult } from "@/components/assignments/side-panels";
import { Alert } from "@/components/ui";
import { useLocale, useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { countWords, workspaceError } from "@/lib/assignments";
import { bcp47 } from "@/lib/format";
import type { AssignmentDetail, AssignmentRun } from "@/lib/types";

/** Feedback on the draft as it is saved: the latest, with the rubric check when there is a
 *  rubric, and the earlier rounds so the student can see whether the draft improved. The AI
 *  coaches (what is missing, what to clarify); it never rewrites the assignment. */
export function FeedbackTab({
  detail,
  starting,
  blocked,
  onAsk,
}: {
  detail: AssignmentDetail;
  starting: boolean;
  blocked: string | null;
  onAsk: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const latest = detail.latest_runs.find((run) => run.kind === "feedback");
  const ready = latest?.status === "ready" && latest.result ? latest : null;
  const [picked, setPicked] = useState<number | null>(null);
  const [earlier, setEarlier] = useState<AssignmentRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  // The list of every round is fetched again whenever the newest one changes.
  const marker = `${latest?.id ?? ""}:${latest?.status ?? ""}`;
  useEffect(() => {
    let live = true;
    api<AssignmentRun[]>(`/assignments/${detail.id}/runs`)
      .then((runs) => {
        if (live) setEarlier(runs.filter((run) => run.kind === "feedback" && run.status === "ready" && run.id !== latest?.id));
      })
      .catch((caught: unknown) => {
        if (live) setError(workspaceError(caught, t));
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.id, marker, t]);

  const when = (iso: string) => new Intl.DateTimeFormat(bcp47(locale), { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
  const words = countWords(detail.draft);

  return (
    <div className="space-y-3 p-3.5">
      <p className="text-xs text-muted">{t("aw2.fb.intro")}</p>
      <p className="tabular text-xs text-muted">{t("aw2.fb.draftNow", { words })}</p>
      <RunButton run={latest} starting={starting} blocked={blocked} onAsk={onAsk} label={t("aw2.fb.run")} primary />
      {blocked ? <p className="text-xs text-muted">{blocked}</p> : null}
      <RunState run={latest} idle={null} />
      {ready ? (
        <>
          <p className="tabular text-xs text-muted">{t("aw2.fb.given", { when: when(ready.finished_at ?? ready.created_at) })}</p>
          <RunResult run={ready} rubric={detail.rubric} assignmentId={detail.id} picked={picked} onPick={setPicked} />
        </>
      ) : null}

      {error ? <Alert>{error}</Alert> : null}
      {earlier && earlier.length > 0 ? (
        <section aria-label={t("aw2.fb.earlier")} className="border-t border-border pt-3">
          <h3 className="mb-1.5 text-[13px] font-semibold">{t("aw2.fb.earlier")}</h3>
          <ul className="divide-y divide-border rounded-xl border border-border">
            {earlier.map((run) => (
              <li key={run.id}>
                <button
                  type="button"
                  aria-expanded={open === run.id}
                  onClick={() => setOpen(open === run.id ? null : run.id)}
                  className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px] hover:bg-surface-2"
                >
                  <span className="tabular min-w-0 flex-1">{when(run.finished_at ?? run.created_at)}</span>
                  <ChevronDown className={`h-4 w-4 shrink-0 text-faint transition-transform ${open === run.id ? "rotate-180" : ""}`} aria-hidden />
                </button>
                {open === run.id ? (
                  <div className="border-t border-border px-2.5 pb-3 pt-2">
                    <RunResult run={run} rubric={detail.rubric} assignmentId={detail.id} picked={null} onPick={() => undefined} />
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
