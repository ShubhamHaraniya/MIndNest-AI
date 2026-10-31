"use client";

import { ChevronDown, Library } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/kit/button";
import { Popover } from "@/components/kit/popover";
import { useT } from "@/i18n/client";
import { api } from "@/lib/api";
import { ALL_COURSES, MAX_SCOPE_FILES, type ScopeKind, type ScopeValue } from "@/lib/chat";
import type { Material, Subject } from "@/lib/types";

/** The short text on the button: what the next questions may search. */
export function scopeLabel(scope: ScopeValue, subjects: Subject[], t: ReturnType<typeof useT>): string {
  if (scope.kind === "subject") return subjects.find((s) => s.id === scope.subjectId)?.name ?? t("cw.scopeAll");
  if (scope.kind === "materials") return t("chx.scope.files", { count: scope.materialIds.length });
  return t("cw.scopeAll");
}

/** Choose what the chat may search: every course, one course, or specific files (up to 50, from
 *  any course). Changes are applied with the button, so a half-made choice never reaches the
 *  conversation. */
export function ScopePicker({
  subjects,
  scope,
  disabled,
  onApply,
}: {
  subjects: Subject[];
  scope: ScopeValue;
  disabled: boolean;
  onApply: (scope: ScopeValue) => void;
}) {
  const t = useT();
  const [draft, setDraft] = useState<ScopeValue>(scope);
  const [browse, setBrowse] = useState("");
  const [files, setFiles] = useState<Record<string, Material[] | "error">>({});
  const [filter, setFilter] = useState("");

  function reset() {
    setDraft(scope);
    setBrowse(scope.subjectId || subjects[0]?.id || "");
    setFilter("");
  }

  // The files of the course being browsed are fetched once and kept while the menu is used.
  const listed = files[browse];
  useEffect(() => {
    if (draft.kind !== "materials" || !browse || files[browse] !== undefined) return;
    let live = true;
    api<Material[]>(`/subjects/${browse}/materials`)
      .then((items) => live && setFiles((previous) => ({ ...previous, [browse]: items.filter((m) => m.status === "ready") })))
      .catch(() => live && setFiles((previous) => ({ ...previous, [browse]: "error" })));
    return () => {
      live = false;
    };
  }, [draft.kind, browse, files]);

  const shown = useMemo(() => {
    if (!Array.isArray(listed)) return [];
    const needle = filter.trim().toLowerCase();
    return needle ? listed.filter((m) => m.filename.toLowerCase().includes(needle)) : listed;
  }, [listed, filter]);

  const picked = new Set(draft.materialIds);
  const full = picked.size >= MAX_SCOPE_FILES;
  const canApply =
    draft.kind === "all" ||
    (draft.kind === "subject" && draft.subjectId !== "") ||
    (draft.kind === "materials" && draft.materialIds.length > 0);

  function setKind(kind: ScopeKind) {
    setDraft((current) => ({
      ...current,
      kind,
      subjectId: kind === "subject" && !current.subjectId ? (subjects[0]?.id ?? "") : current.subjectId,
    }));
  }

  function toggle(id: string) {
    setDraft((current) => {
      const has = current.materialIds.includes(id);
      if (!has && current.materialIds.length >= MAX_SCOPE_FILES) return current;
      return {
        ...current,
        materialIds: has ? current.materialIds.filter((m) => m !== id) : [...current.materialIds, id],
      };
    });
  }

  const options: { value: ScopeKind; label: string; hint: string }[] = [
    { value: "all", label: t("chx.scope.all"), hint: t("chx.scope.allHint") },
    { value: "subject", label: t("chx.scope.course"), hint: t("chx.scope.courseHint") },
    { value: "materials", label: t("chx.scope.pick"), hint: t("chx.scope.pickHint", { max: MAX_SCOPE_FILES }) },
  ];

  return (
    <Popover
      label={t("cw.scope")}
      align="start"
      side="top"
      panelClassName="w-[min(24rem,90vw)] p-3"
      onOpenChange={(open) => {
        if (open) reset();
      }}
      trigger={({ toggle: open, open: isOpen, id }) => (
        <button
          type="button"
          data-popover-trigger
          disabled={disabled}
          aria-expanded={isOpen}
          aria-controls={isOpen ? id : undefined}
          onClick={open}
          title={t("chx.scope.title")}
          className="flex h-7 max-w-[13rem] items-center gap-1 rounded border border-transparent px-1.5 text-xs text-muted hover:border-border hover:text-ink disabled:opacity-60 disabled:hover:border-transparent"
        >
          <Library className="h-3 w-3 shrink-0" aria-hidden />
          <span className="truncate">{scopeLabel(scope, subjects, t)}</span>
          <ChevronDown className="h-3 w-3 shrink-0" aria-hidden />
        </button>
      )}
    >
      {(close) => (
        <div className="space-y-3 text-xs">
          <p className="font-medium text-ink">{t("chx.scope.title")}</p>
          <div role="radiogroup" aria-label={t("chx.scope.title")} className="space-y-1">
            {options.map((option) => (
              <label key={option.value} className="flex cursor-pointer items-start gap-2 rounded px-1 py-1 hover:bg-surface-2">
                <input
                  type="radio"
                  name="chat-scope"
                  checked={draft.kind === option.value}
                  onChange={() => setKind(option.value)}
                  className="mt-0.5 accent-primary"
                />
                <span>
                  <span className="block text-[13px] text-ink">{option.label}</span>
                  <span className="block text-muted">{option.hint}</span>
                </span>
              </label>
            ))}
          </div>

          {draft.kind === "subject" ? (
            <select
              value={draft.subjectId}
              onChange={(event) => setDraft((current) => ({ ...current, subjectId: event.target.value }))}
              aria-label={t("cw.scope")}
              className="h-8 w-full rounded border border-border bg-surface px-2 text-[13px] text-ink"
            >
              {subjects.map((subject) => (
                <option key={subject.id} value={subject.id}>
                  {subject.name}
                </option>
              ))}
            </select>
          ) : null}

          {draft.kind === "materials" ? (
            <div className="space-y-2">
              <select
                value={browse}
                onChange={(event) => {
                  setBrowse(event.target.value);
                  setFilter("");
                }}
                aria-label={t("cw.scope")}
                className="h-8 w-full rounded border border-border bg-surface px-2 text-[13px] text-ink"
              >
                {subjects.map((subject) => (
                  <option key={subject.id} value={subject.id}>
                    {subject.name}
                  </option>
                ))}
              </select>
              <input
                type="search"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder={t("chx.scope.filter")}
                aria-label={t("chx.scope.filter")}
                className="h-8 w-full rounded border border-border bg-surface px-2 text-[13px] placeholder:text-faint focus:border-primary focus:outline-none"
              />
              <div className="max-h-48 overflow-y-auto rounded border border-border">
                {listed === "error" ? (
                  <p className="p-2 text-danger">{t("chx.scope.loadFailed")}</p>
                ) : listed === undefined ? (
                  <p className="p-2 text-muted">{t("common.loading")}</p>
                ) : shown.length === 0 ? (
                  <p className="p-2 text-muted">{t("chx.scope.noFiles")}</p>
                ) : (
                  <ul>
                    {shown.map((material) => {
                      const on = picked.has(material.id);
                      return (
                        <li key={material.id}>
                          <label className="flex cursor-pointer items-center gap-2 px-2 py-1 hover:bg-surface-2">
                            <input
                              type="checkbox"
                              checked={on}
                              disabled={!on && full}
                              onChange={() => toggle(material.id)}
                              className="accent-primary"
                            />
                            <span className="min-w-0 flex-1 truncate text-[13px]" title={material.filename}>
                              {material.filename}
                            </span>
                            {material.module ? <span className="shrink-0 text-faint">{material.module}</span> : null}
                          </label>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
              <p className="flex items-center justify-between text-muted">
                <span>{t("chx.scope.selected", { count: picked.size, max: MAX_SCOPE_FILES })}</span>
                {picked.size > 0 ? (
                  <button
                    type="button"
                    onClick={() => setDraft((current) => ({ ...current, materialIds: [] }))}
                    className="underline hover:text-ink"
                  >
                    {t("common.clear")}
                  </button>
                ) : null}
              </p>
              {full ? <p className="text-warning">{t("chx.scope.full", { max: MAX_SCOPE_FILES })}</p> : null}
            </div>
          ) : null}

          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button
              size="sm"
              disabled={!canApply}
              onClick={() => {
                onApply(
                  draft.kind === "all"
                    ? ALL_COURSES
                    : draft.kind === "subject"
                      ? { kind: "subject", subjectId: draft.subjectId, materialIds: [] }
                      : { kind: "materials", subjectId: "", materialIds: draft.materialIds },
                );
                close();
              }}
            >
              {t("chx.scope.apply")}
            </Button>
          </div>
        </div>
      )}
    </Popover>
  );
}
