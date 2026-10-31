"use client";

import { ListChecks } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/kit/button";
import { SearchField, Segmented, Select } from "@/components/kit/controls";
import { Panel } from "@/components/kit/panel";
import { EmptyState, NoResults } from "@/components/kit/states";
import { useT } from "@/i18n/client";
import { taskTitle } from "@/lib/planner";

import { FILTERS, countStates, matchesFilter, type TaskFilter } from "./model";
import { TaskList, type TaskActions } from "./task-row";
import type { Planner } from "./use-planner";

/** Every task in one list, filtered by state, course and words. */
export function TasksView({
  planner,
  actions,
  onAdd,
  today,
}: {
  planner: Planner;
  actions: TaskActions;
  onAdd: (day: string) => void;
  today: string;
}) {
  const t = useT();
  const [filter, setFilter] = useState<TaskFilter>("open");
  const [subject, setSubject] = useState("");
  const [query, setQuery] = useState("");

  const counts = useMemo(() => countStates(planner.tasks), [planner.tasks]);
  const subjects = useMemo(() => {
    const seen = new Map<string, string>();
    for (const task of planner.tasks) if (task.subject_id && task.subject_name) seen.set(task.subject_id, task.subject_name);
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [planner.tasks]);

  const shown = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return planner.tasks.filter(
      (task) =>
        matchesFilter(task, filter) &&
        (!subject || task.subject_id === subject) &&
        (!needle || taskTitle(task, t).toLocaleLowerCase().includes(needle)),
    );
  }, [planner.tasks, filter, subject, query, t]);

  const options = FILTERS.map((value) => ({
    value,
    label: t(`pl.filter.${value}` as const),
    count:
      value === "open"
        ? counts.pending + counts.overdue
        : value === "all"
          ? planner.tasks.length
          : counts[value === "completed" ? "completed" : value === "overdue" ? "overdue" : "cancelled"],
  }));

  if (planner.tasks.length === 0) {
    return (
      <EmptyState icon={ListChecks} title={t("pl.tasks.emptyTitle")} description={t("pl.tasks.emptyBody")}>
        <Button onClick={() => onAdd(today)}>{t("pl.addTask")}</Button>
      </EmptyState>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented value={filter} onChange={setFilter} options={options} label={t("pl.filter.label")} />
        <SearchField value={query} onChange={setQuery} placeholder={t("pl.tasks.search")} className="w-full sm:w-56" />
        {subjects.length > 1 ? (
          <Select value={subject} onChange={(event) => setSubject(event.target.value)} aria-label={t("assign.create.subject")} className="w-auto">
            <option value="">{t("pl.tasks.allSubjects")}</option>
            {subjects.map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </Select>
        ) : null}
      </div>
      <Panel id="all-tasks" title={t("pl.mode.tasks")} description={t("pl.tasks.count", { count: shown.length })}>
        {shown.length === 0 ? (
          <NoResults title={t("pl.tasks.noneTitle")} description={t("pl.tasks.noneBody")} />
        ) : (
          <TaskList tasks={shown} actions={actions} today={today} showDay label={t("pl.mode.tasks")} />
        )}
      </Panel>
    </div>
  );
}
