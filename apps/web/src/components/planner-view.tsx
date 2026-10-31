"use client";

import { CalendarPlus, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/kit/button";
import { Segmented } from "@/components/kit/controls";
import { ConfirmDialog } from "@/components/kit/confirm";
import { ErrorState } from "@/components/kit/states";
import { Skeleton } from "@/components/kit/skeleton";
import { useT } from "@/i18n/client";
import { taskTitle } from "@/lib/planner";
import type { StudyTask, Subject } from "@/lib/types";

import { ExamsPanel } from "./planner/exams-panel";
import { MODES, stateOf, type PlannerMode } from "./planner/model";
import { MonthView } from "./planner/month-view";
import { OverloadBanner } from "./planner/overload-banner";
import { PlanDialog } from "./planner/plan-dialog";
import { PlanHero } from "./planner/plan-hero";
import { PrefsPanel } from "./planner/prefs-panel";
import { TaskDialog } from "./planner/task-dialog";
import type { TaskActions } from "./planner/task-row";
import { TasksView } from "./planner/tasks-view";
import { TimelineView } from "./planner/timeline-view";
import { TodayView } from "./planner/today-view";
import { usePlanner } from "./planner/use-planner";
import { WeekView } from "./planner/week-view";

/** The study planner: Today, Week, Month, Timeline and Tasks over the same list of tasks, with the
 *  plan maker, study time and exams beside them. */
export function PlannerView({ subjects }: { subjects: Subject[] }) {
  const t = useT();
  const planner = usePlanner();
  const [mode, setMode] = useState<PlannerMode>("today");
  const [anchor, setAnchor] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ task: StudyTask | null; day: string } | null>(null);
  const [deleting, setDeleting] = useState<StudyTask | null>(null);
  const [planning, setPlanning] = useState(false);
  const today = planner.today;

  const actions: TaskActions = useMemo(
    () => ({
      onToggle: (task) => void planner.update(task, { status: stateOf(task) === "completed" ? "todo" : "done" }),
      onCancel: (task) => void planner.update(task, { status: "cancelled" }),
      onRestore: (task) => void planner.update(task, { status: "todo" }),
      onEdit: (task) => setDialog({ task, day: task.planned_for }),
      onDelete: (task) => setDeleting(task),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [planner.update],
  );

  if (planner.error && !today) {
    return <ErrorState compact description={planner.error} onRetry={() => void planner.reload()} />;
  }
  if (planner.loading || !today) {
    return (
      <div className="space-y-3" aria-hidden>
        <Skeleton className="h-9 w-80" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  const day = anchor ?? today;
  const hasPlan = planner.tasks.some((task) => task.source === "plan" && task.status === "todo");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Segmented
          value={mode}
          onChange={setMode}
          label={t("pl.mode.label")}
          options={MODES.map((value) => ({ value, label: t(`pl.mode.${value}` as const) }))}
        />
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" onClick={() => setDialog({ task: null, day: mode === "today" ? today : day })}>
            <CalendarPlus className="h-3.5 w-3.5" aria-hidden />
            {t("pl.addTask")}
          </Button>
          <Button size="sm" onClick={() => setPlanning(true)}>
            <Sparkles className="h-3.5 w-3.5" aria-hidden />
            {hasPlan ? t("planner.make.again") : t("planner.make.button")}
          </Button>
        </div>
      </div>

      <PlanHero planner={planner} actions={actions} today={today} onAdd={(target) => setDialog({ task: null, day: target })} />

      <OverloadBanner
        planner={planner}
        onShowDay={(target) => {
          setAnchor(target);
          setMode("week");
        }}
      />

      {mode === "today" ? <TodayView planner={planner} actions={actions} today={today} onAdd={(target) => setDialog({ task: null, day: target })} /> : null}
      {mode === "week" ? (
        <WeekView
          planner={planner}
          anchor={day}
          onAnchor={setAnchor}
          today={today}
          onToggle={actions.onToggle}
          onOpen={actions.onEdit}
          onAdd={(target) => setDialog({ task: null, day: target })}
        />
      ) : null}
      {mode === "month" ? (
        <MonthView planner={planner} anchor={day} onAnchor={setAnchor} actions={actions} today={today} onAdd={(target) => setDialog({ task: null, day: target })} />
      ) : null}
      {mode === "timeline" ? <TimelineView planner={planner} actions={actions} today={today} /> : null}
      {mode === "tasks" ? <TasksView planner={planner} actions={actions} today={today} onAdd={(target) => setDialog({ task: null, day: target })} /> : null}

      <div className="grid gap-4 lg:grid-cols-2">
        {planner.prefs ? <PrefsPanel prefs={planner.prefs} onSave={planner.savePreferences} /> : null}
        <ExamsPanel exams={planner.exams} subjects={subjects} onChanged={() => void planner.reload()} />
      </div>

      <TaskDialog
        open={dialog !== null}
        task={dialog?.task ?? null}
        defaultDay={dialog?.day ?? today}
        subjects={subjects}
        onClose={() => setDialog(null)}
        onAdd={planner.add}
        onUpdate={planner.update}
      />

      <PlanDialog open={planning} hasPlan={hasPlan} onClose={() => setPlanning(false)} onGenerate={planner.generate} />

      <ConfirmDialog
        open={deleting !== null}
        title={t("pl.delete.title", { name: deleting ? taskTitle(deleting, t) : "" })}
        description={deleting?.source === "plan" ? t("pl.delete.planBody") : t("pl.delete.body")}
        confirmLabel={t("common.delete")}
        onConfirm={async () => {
          if (deleting) await planner.remove(deleting);
        }}
        onClose={() => setDeleting(null)}
      />
    </div>
  );
}
