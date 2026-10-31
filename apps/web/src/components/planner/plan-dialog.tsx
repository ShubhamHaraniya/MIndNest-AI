"use client";

import { useState } from "react";

import { Dialog } from "@/components/dialog";
import { Button } from "@/components/kit/button";
import { FormRow, Select } from "@/components/kit/controls";
import { useT } from "@/i18n/client";
import type { GenerateResult } from "@/lib/types";

const HORIZONS = [7, 14, 21, 28];

/** Make (or remake) the plan. It says what is kept: the student's own tasks and everything they
 *  finished, cancelled or moved are never replaced or planned again. */
export function PlanDialog({
  open,
  hasPlan,
  onClose,
  onGenerate,
}: {
  open: boolean;
  hasPlan: boolean;
  onClose: () => void;
  onGenerate: (days: number) => Promise<GenerateResult | null>;
}) {
  const t = useT();
  const [days, setDays] = useState(14);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<GenerateResult | null>(null);

  function close() {
    setResult(null);
    onClose();
  }

  async function run() {
    setBusy(true);
    try {
      setResult(await onGenerate(days));
    } finally {
      setBusy(false);
    }
  }

  const message = !result
    ? null
    : result.notice === "nothing_to_plan"
      ? t("planner.nothing")
      : result.notice === "up_to_date"
        ? t("pl.make.upToDate", { handled: result.already_handled })
        : t("pl.make.done", { created: result.created, kept: result.kept, handled: result.already_handled });

  return (
    <Dialog open={open} onClose={close} title={hasPlan ? t("planner.make.again") : t("planner.make.title")}>
      <div className="space-y-4">
        <p className="text-[13px] text-muted">{t("planner.make.intro")}</p>
        <ul className="list-disc space-y-1 pl-5 text-[13px] text-muted">
          <li>{t("pl.make.keepManual")}</li>
          <li>{t("pl.make.keepDone")}</li>
          <li>{t("pl.make.keepMoved")}</li>
          <li>{t("pl.make.replaces")}</li>
        </ul>
        <FormRow label={t("planner.make.days")} htmlFor="plan-days">
          <Select id="plan-days" value={days} onChange={(event) => setDays(Number(event.target.value))}>
            {HORIZONS.map((count) => (
              <option key={count} value={count}>
                {t("planner.make.nextDays", { count })}
              </option>
            ))}
          </Select>
        </FormRow>
        {message ? (
          <p role="status" className="rounded border border-border bg-surface-2 px-3 py-2 text-[13px]">
            {message}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={close} disabled={busy}>
            {result ? t("common.close") : t("common.cancel")}
          </Button>
          <Button loading={busy} onClick={() => void run()}>
            {hasPlan || result ? t("planner.make.again") : t("planner.make.button")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
