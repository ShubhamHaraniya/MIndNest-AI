"""The Planner agent: exams, study tasks and the study plan, by chat.

It calls the same functions the Planner and Calendar pages use, as the signed-in student, so the
same checks, limits and privacy rules apply. The plan itself is made by fixed rules (no AI), so
"make me a plan" is instant. This agent never deletes anything: it adds, reschedules, and marks
tasks done or skipped."""

from datetime import date, timedelta
from typing import Any, Literal
from uuid import UUID

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from mindnest_core.plannerlogic import DEFAULT_HORIZON, MAX_HORIZON, MIN_HORIZON
from pydantic import BaseModel, Field

from mindnest_api.agent.agents.common import NoArgs, list_subjects_tool, today_line
from mindnest_api.agent.context import AgentContext
from mindnest_api.agent.registry import AgentSpec, Prepared, base_prompt, chat_messages, earlier_work, register
from mindnest_api.agent.router import PlanStep
from mindnest_api.agent.tools import ToolFailure, agent_tool, via_route
from mindnest_api.routes import planner as planner_routes

ROLE = """You help the student plan their studying: exams, daily study tasks and the study plan.

- {today} Turn dates such as "next Friday" or "in two weeks" into YYYY-MM-DD yourself, from today's \\
date. If a date is unclear, ask ONE short question instead of guessing.
- Add an exam with add_exam. Add a single study task with add_task. Change a task's date or mark it \\
done or skipped with update_task. See what is planned with list_tasks and list_exams.
- "Make me a plan" or "plan my revision": call list_exams first, then generate_plan. The plan is \\
made by fixed rules from the exams, assignments, due flashcards and weak subjects, and it only adds \\
tasks that are not already there.
- A task has a day and a length in minutes, never a clock time or a place on Google Calendar. Never \
say a task is "at 6 pm" or "on your Google Calendar". If the student gave a clock time, say the planner \
keeps only the day and length, and that they can ask you to "add it to my Google Calendar" (a different \
helper does that, with their approval), or use Send to Google on the Calendar page.
- You cannot delete exams or tasks. If asked, tell the student to do it on the Planner page.
- After a change, say in one or two sentences what changed. Never say something was added or \\
changed unless a tool result confirms it.
- Never invent ids: use the ids from tool results."""


def _subject_id(ctx: AgentContext, subject: str | None) -> UUID | None:
    if not subject:
        return None
    found = ctx.find_subject(subject)
    if found is None:
        raise ToolFailure(f"No subject matches '{subject}'. Their subjects are: {ctx.subject_names()}.")
    return found.id


def _uuid(value: str, what: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise ToolFailure(f"That is not a valid {what} id. Use an id from a tool result.") from exc


async def _list_exams(ctx: AgentContext) -> str:
    exams = await via_route(planner_routes.list_exams(ctx.user, ctx.db))
    if not exams:
        return "The student has no exams saved."
    return "\n".join(
        f"- id {e.id} | {e.title} | {e.exam_on.isoformat()} | {e.days_left} days left"
        + (f" | {e.subject_name}" if e.subject_name else "")
        for e in exams
    )


class AddExamArgs(BaseModel):
    title: str = Field(description="Short exam name, e.g. 'Operating Systems midterm'.", min_length=1, max_length=120)
    day: date = Field(description="The exam day, YYYY-MM-DD.")
    subject: str | None = Field(default=None, description="One of the student's subjects, if it clearly belongs to one.")
    notes: str = Field(default="", max_length=1000)


async def _add_exam(ctx: AgentContext, title: str, day: date, subject: str | None = None, notes: str = "") -> str:
    body = planner_routes.ExamIn(title=title, exam_on=day, subject_id=_subject_id(ctx, subject), notes=notes)
    exam = await via_route(planner_routes.create_exam(body, ctx.user, ctx.db, ctx.limiter))
    ctx.emit({"type": "card", "kind": "exam", "data": {
        "id": str(exam.id), "title": exam.title, "exam_on": exam.exam_on.isoformat(),
        "days_left": exam.days_left, "subject": exam.subject_name}})
    return f"Exam saved: id {exam.id}, '{exam.title}' on {exam.exam_on.isoformat()} ({exam.days_left} days left)."


class ListTasksArgs(BaseModel):
    first: date | None = Field(default=None, description="First day, YYYY-MM-DD. Default: today.")
    last: date | None = Field(default=None, description="Last day, YYYY-MM-DD. Default: two weeks after the first day.")


async def _list_tasks(ctx: AgentContext, first: date | None = None, last: date | None = None) -> str:
    result = await via_route(planner_routes.list_tasks(ctx.user, ctx.db, first, last))
    if not result.items:
        return "No study tasks are planned in that period."
    ctx.emit({"type": "card", "kind": "plan", "data": _plan_card(result.items, str(result.today))})
    return "\n".join(
        f"- id {t.id} | {t.planned_for.isoformat()} | {t.title} | {t.minutes} min | {t.status}"
        + (f" | {t.subject_name}" if t.subject_name else "")
        for t in result.items[:60]
    )


def _plan_card(items: list[Any], today: str) -> dict[str, Any]:
    return {
        "today": today, "total": len(items),
        "items": [
            {"id": str(t.id), "day": t.planned_for.isoformat(), "title": t.title, "minutes": t.minutes,
             "status": t.status, "subject": t.subject_name}
            for t in items[:14]
        ],
    }


class AddTaskArgs(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    day: date = Field(description="The day to do it, YYYY-MM-DD.")
    minutes: int = Field(default=30, ge=5, le=480)
    subject: str | None = None


async def _add_task(ctx: AgentContext, title: str, day: date, minutes: int = 30, subject: str | None = None) -> str:
    body = planner_routes.TaskIn(title=title, planned_for=day, minutes=minutes, subject_id=_subject_id(ctx, subject))
    task = await via_route(planner_routes.create_task(body, ctx.user, ctx.db, ctx.limiter))
    ctx.emit({"type": "card", "kind": "plan", "data": _plan_card([task], day.isoformat())})
    return f"Task added: id {task.id}, '{task.title}' on {task.planned_for.isoformat()} for {task.minutes} minutes."


class UpdateTaskArgs(BaseModel):
    task_id: str = Field(description="A task id from list_tasks.")
    day: date | None = Field(default=None, description="Move the task to this day, YYYY-MM-DD.")
    status: Literal["todo", "done", "cancelled", "skipped"] | None = None
    minutes: int | None = Field(default=None, ge=5, le=480)


async def _update_task(
    ctx: AgentContext, task_id: str, day: date | None = None, status: str | None = None, minutes: int | None = None
) -> str:
    changes: dict[str, Any] = {}
    if day is not None:
        changes["planned_for"] = day
    if status is not None:
        changes["status"] = status
    if minutes is not None:
        changes["minutes"] = minutes
    if not changes:
        raise ToolFailure("Nothing to change: give a date, a status or minutes.")
    body = planner_routes.TaskPatch(**changes)
    task = await via_route(planner_routes.update_task(_uuid(task_id, "task"), body, ctx.user, ctx.db))
    return f"Task updated: '{task.title}' is now {task.status} on {task.planned_for.isoformat()} ({task.minutes} min)."


class GenerateArgs(BaseModel):
    days: int = Field(default=DEFAULT_HORIZON, ge=MIN_HORIZON, le=MAX_HORIZON, description="How many days ahead to plan.")


async def _generate_plan(ctx: AgentContext, days: int = DEFAULT_HORIZON) -> str:
    made = await via_route(planner_routes.generate_plan(planner_routes.GenerateIn(days=days), ctx.user, ctx.db, ctx.limiter))
    if made.notice == "nothing_to_plan":
        return (
            "Nothing was planned: the student has no exams, dated assignments, due flashcards or weak "
            "subjects yet. Suggest adding an exam first."
        )
    tasks = await via_route(planner_routes.list_tasks(ctx.user, ctx.db, made.first_day, min(made.last_day, made.first_day + timedelta(days=13))))
    ctx.emit({"type": "card", "kind": "plan", "data": _plan_card(tasks.items, str(tasks.today))})
    return f"Plan generated: {made.created} new task(s) from {made.first_day.isoformat()} to {made.last_day.isoformat()}."


def planner_tools(ctx: AgentContext) -> list[Any]:
    return [
        agent_tool(ctx, "planner", "list_exams", "List the student's saved exams.", NoArgs, _list_exams, lambda a: ""),
        agent_tool(ctx, "planner", "add_exam", "Save an exam with its date.", AddExamArgs, _add_exam,
                   lambda a: f"{a.get('title', '')} · {a.get('day', '')}"),
        agent_tool(ctx, "planner", "list_tasks", "List planned study tasks in a date range.", ListTasksArgs, _list_tasks,
                   lambda a: f"{a.get('first') or 'today'} → {a.get('last') or ''}"),
        agent_tool(ctx, "planner", "add_task", "Add one study task on a day.", AddTaskArgs, _add_task,
                   lambda a: f"{a.get('title', '')} · {a.get('day', '')}"),
        agent_tool(ctx, "planner", "update_task", "Move a task to another day, change its minutes, or mark it done or skipped.",
                   UpdateTaskArgs, _update_task, lambda a: a.get("status") or str(a.get("day") or "")),
        agent_tool(ctx, "planner", "generate_plan", "Make the study plan for the next days from exams, assignments, due flashcards and weak subjects.",
                   GenerateArgs, _generate_plan, lambda a: f"{a.get('days', DEFAULT_HORIZON)} days"),
        list_subjects_tool(ctx, "planner"),
    ]


async def prepare(
    ctx: AgentContext, step: PlanStep, results: list[dict[str, Any]], config: RunnableConfig
) -> Prepared:
    system = base_prompt(ctx, "planner agent", ROLE.format(today=today_line(ctx)),
                         f"\nThe student's subjects: {ctx.subject_names()}." + earlier_work(results))
    return Prepared(system, [*chat_messages(ctx.history), HumanMessage(ctx.question)])


register(
    AgentSpec(
        "planner", "planner agent",
        "saves exams, adds and reschedules study tasks, marks tasks done, shows what is planned, "
        "and makes the study plan or revision schedule.",
        prepare, planner_tools,
    )
)
