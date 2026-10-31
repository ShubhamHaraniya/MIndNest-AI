"use client";

import clsx from "clsx";
import { AlertCircle, Check, ChevronDown, Hourglass, Loader2, ShieldAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { useT } from "@/i18n/client";
import type { MessageKey } from "@/i18n/translate";
import type { AgentRoute, AgentStep } from "@/lib/types";

const AGENTS = ["direct", "study", "quiz", "materials", "planner", "assignment", "calendar", "guardrails"] as const;
const GUARD_RAILS = ["input", "tool_call", "tool_result", "output"] as const;
const TOOLS = [
  "search_materials",
  "list_subjects",
  "create_quiz",
  "start_quiz",
  "list_quizzes",
  "start_revision",
  "list_materials",
  "read_material",
  "get_material_overview",
  "list_exams",
  "add_exam",
  "list_tasks",
  "add_task",
  "update_task",
  "generate_plan",
  "list_assignments",
  "get_assignment",
  "add_assignment",
  "update_assignment",
  "get_help",
  "calendar_status",
  "list_events",
  "add_event",
  "move_event",
  "remove_event",
] as const;

/** The agent's name in the student's language; an unknown name is shown as it is. */
export function agentLabel(name: string, t: (key: MessageKey) => string): string {
  return (AGENTS as readonly string[]).includes(name) ? t(`chat.agent.${name}` as MessageKey) : name;
}

/** What a safety-check step says, in the student's language. The server's own summary is a short
 *  English label list, so only its first word (stopped, cleaned, passed) is used. */
function guardText(step: AgentStep, t: (key: MessageKey) => string): string {
  const rail = (GUARD_RAILS as readonly string[]).includes(step.tool ?? "") ? step.tool : "input";
  const outcome = step.summary.startsWith("stopped")
    ? "stopped"
    : step.summary.startsWith("cleaned")
      ? "cleaned"
      : step.summary.includes("second opinion")
        ? "reviewed"
        : "passed";
  return `${t(`chat.guard.${rail}` as MessageKey)} · ${t(`chat.guard.result.${outcome}` as MessageKey)}`;
}

function toolLabel(name: string, t: (key: MessageKey) => string): string {
  return (TOOLS as readonly string[]).includes(name) ? t(`chat.tool.${name}` as MessageKey) : name;
}

/** What the agents did for this answer: who was chosen, and each tool they used. Open while the
 *  answer is being written, then folded away to one line. */
export function StepsTimeline({
  steps,
  route,
  live,
}: {
  steps: AgentStep[];
  route: AgentRoute | null;
  live: boolean;
}) {
  const t = useT();
  const [manual, setManual] = useState<boolean | null>(null);
  const toolSteps = steps.filter((step) => step.tool !== null);
  if (!route && steps.length === 0) return null;
  // Quick replies ("hi", "thanks") have nothing worth showing.
  if (!live && toolSteps.length === 0 && route?.agents.every((agent) => agent === "direct")) return null;

  const open = manual ?? live;
  const guardOnly = !route && steps.length > 0 && steps.every((step) => step.agent === "guardrails");
  const names = guardOnly
    ? agentLabel("guardrails", t)
    : (route?.agents ?? []).map((agent) => agentLabel(agent, t)).join(" → ");
  const running = steps.some((step) => step.status === "running");
  const waiting = steps.some((step) => step.status === "waiting");

  return (
    <div className="mb-3 rounded-2xl border border-border bg-bg/40 text-xs">
      <button
        type="button"
        onClick={() => setManual(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-muted hover:text-ink"
      >
        {waiting ? (
          <Hourglass className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
        ) : live && running ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" aria-hidden />
        ) : (
          <Check className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
        )}
        <span className="min-w-0 flex-1 truncate">
          {names ? <span className="font-medium text-ink">{names}</span> : t("chat.steps.working")}
          {toolSteps.length > 0 ? ` · ${t("chat.steps.count", { n: toolSteps.length })}` : ""}
        </span>
        <ChevronDown className={clsx("h-3.5 w-3.5 shrink-0 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open ? (
        <ol className="space-y-2 border-t border-border px-3.5 py-2.5">
          {route ? (
            <li className="flex items-start gap-2 text-muted">
              <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
              <span>
                {route.shortcut ? t("chat.steps.quick") : t("chat.steps.chose", { agents: names })}
                {route.ms !== undefined && !route.shortcut ? ` · ${route.ms} ms` : ""}
              </span>
            </li>
          ) : null}
          {steps.map((step) => (
            <li key={step.id} className="flex items-start gap-2">
              {step.status === "running" ? (
                <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-primary" aria-hidden />
              ) : step.status === "waiting" ? (
                <Hourglass className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
              ) : step.status === "failed" ? (
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" aria-hidden />
              ) : step.status === "blocked" ? (
                <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" aria-hidden />
              ) : step.agent === "guardrails" ? (
                <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
              ) : (
                <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
              )}
              <span className={clsx("min-w-0", step.status === "failed" || step.status === "blocked" ? "text-danger" : "text-ink")}>
                {step.agent === "guardrails" ? (
                  <span>{guardText(step, t)}</span>
                ) : step.tool === null ? (
                  <span className="font-medium">{t("chat.steps.started", { agent: agentLabel(step.agent, t) })}</span>
                ) : (
                  <>
                    {toolLabel(step.tool, t)}
                    {step.summary ? <span className="text-muted"> · {step.summary}</span> : null}
                    {step.status === "failed" ? <span> · {t("chat.steps.failed")}</span> : null}
                    {step.status === "waiting" ? <span className="text-muted"> · {t("chat.steps.waiting")}</span> : null}
                  </>
                )}
                {step.ms !== undefined && step.status !== "running" ? (
                  <span className="text-muted"> · {step.ms} ms</span>
                ) : null}
              </span>
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}
