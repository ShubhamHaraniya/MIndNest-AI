"""The Calendar agent: shows, adds, moves and removes events on the student's Google Calendar.

Everything goes through the calendar MCP server (see calendar_gateway), never straight to Google.
It works on one calendar only: "MindNest AI", which MindNest made inside the student's own Google
Calendar. Google's permission (`calendar.app.created`) does not let MindNest see or change
anything else there.

Changing the calendar needs the student's yes. Each add, move or remove builds a proposal and
PAUSES the run (langgraph `interrupt`); the chat shows the proposal as a card with Approve,
Edit and Cancel. Nothing is sent to Google until the student approves, and what is sent is what
the card showed (plus any edits they made). Reading the calendar needs no approval."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from mindnest_core.calevent import EventEdits, EventIn, apply_edits
from mindnest_core.plannerlogic import local_today, local_zone
from pydantic import BaseModel, Field, ValidationError

from mindnest_api.agent.agents.common import NoArgs, today_line
from mindnest_api.agent.context import AgentContext
from mindnest_api.agent.registry import AgentSpec, Prepared, base_prompt, chat_messages, earlier_work, register
from mindnest_api.agent.router import PlanStep
from mindnest_api.agent.tools import ToolFailure, agent_tool
from mindnest_api.calendar_gateway import CalendarToolError

MAX_LISTED = 25
MAX_DAYS = 31

ROLE = """You manage the student's Google Calendar: you can show it, add events, move events and \\
remove events. You work only on the calendar named "MindNest AI" that MindNest made in their Google \\
Calendar. You cannot see or change their other calendars or events, so never claim to know what else \\
is in their day.

- {today} Turn words like "tomorrow" or "next Friday" into YYYY-MM-DD yourself. If the date or the \\
time is missing or unclear, ask ONE short question first. A time is HH:MM on a 24-hour clock; leave \\
it out for an all-day event. The default length is 60 minutes.
- To see events use list_events (it shows a card, so do not repeat every event in your reply; \\
summarise in a sentence).
- To add use add_event, to change an event use move_event (you need its id: call list_events first), \\
to delete use remove_event. Each of these pauses so the student can approve; the card with the \\
Approve button is shown to them by the app. Ask for ONE change at a time and wait for the result \\
before the next.
- If the tool result says the student approved, say in one sentence what is now on their calendar. \\
If it says they declined, say it is not added and offer to change it. If it says it failed, say \\
plainly what did not work. Never say something was added, moved or removed unless a tool result \\
confirms it.
- If Google Calendar is not connected, tell the student to connect it on the Calendar page. Do not \\
repeat links.
- Never invent event ids: use the ids from tool results."""


# ------------------------------------------------------------------------------ helpers


def _today(ctx: AgentContext) -> date:
    return local_today(ctx.user.timezone, datetime.now(UTC))


def _zone(ctx: AgentContext) -> str:
    return local_zone(ctx.user.timezone).key


def _shown(event: EventIn) -> dict[str, Any]:
    return {
        "summary": event.summary, "description": event.description, "day": event.day.isoformat(),
        "start_time": event.start_time, "minutes": event.minutes, "all_day": event.all_day,
        "timezone": event.timezone,
    }


def _problem(exc: ValidationError) -> ToolFailure:
    parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:4]]
    return ToolFailure("The event is not valid (" + "; ".join(parts) + "). Fix it or ask the student.")


def _failure(ctx: AgentContext, exc: CalendarToolError) -> ToolFailure:
    """What the model is told when the calendar server could not do it."""
    code = exc.code
    if code in ("gcal_not_connected", "gcal_reconnect"):
        ctx.emit({"type": "card", "kind": "calendar_connect",
                  "data": {"reason": "not_connected" if code == "gcal_not_connected" else "reconnect"}})
        return ToolFailure(
            "Google Calendar is not connected." if code == "gcal_not_connected"
            else "Google Calendar needs to be connected again. "
            "Tell the student to connect it on the Calendar page; a button is shown."
        )
    messages = {
        "not_found": "That event is no longer on the calendar.",
        "rate_limited": "Google is busy. Ask the student to try again in a minute.",
        "google_403": "Google refused. The Google Calendar API may not be switched on for this app.",
        "invalid_request": "The calendar service did not accept that request.",
    }
    return ToolFailure(messages.get(code, "The calendar could not be reached right now. Try again later."))


async def _require_calendar(ctx: AgentContext) -> None:
    try:
        status = await ctx.gateway().status(ctx.user.id)
    except CalendarToolError as exc:
        raise _failure(ctx, exc) from exc
    if not status.get("connected"):
        raise _failure(ctx, CalendarToolError("gcal_not_connected"))
    if status.get("needs_reconnect"):
        raise _failure(ctx, CalendarToolError("gcal_reconnect"))
    if not status.get("has_calendar"):
        try:
            await ctx.gateway().ensure_calendar(ctx.user.id)
        except CalendarToolError as exc:
            raise _failure(ctx, exc) from exc


def _proposal_id(ctx: AgentContext, action: str, payload: dict[str, Any]) -> str:
    """The same request always gets the same id, also when the tool runs again after the pause."""
    raw = json.dumps({"run": str(ctx.run_id), "action": action, **payload}, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]  # noqa: S324 (an id, not security)


def _ask(ctx: AgentContext, tool: str, summary: str, proposal: dict[str, Any]) -> tuple[bool, EventEdits | None]:
    """Pause the run and wait for the student. Everything before this line runs again when the run
    resumes, so nothing before it may change anything. Returns (approved, edits)."""
    ctx.emit({"type": "step", "id": ctx.step_id, "agent": "calendar", "tool": tool, "summary": summary[:200],
              "status": "waiting"})
    answer = interrupt({"kind": "calendar_proposal", "proposal": proposal})
    if not isinstance(answer, dict) or not answer.get("approved"):
        return False, None
    raw = answer.get("edits")
    try:
        return True, EventEdits.model_validate(raw) if raw else None
    except ValidationError as exc:
        raise ToolFailure("The student's changes were not valid: " + str(exc.errors()[0]["msg"])) from exc


def _settle(ctx: AgentContext, proposal_id: str, status: str, **extra: Any) -> None:
    ctx.emit({"type": "card_update", "proposal_id": proposal_id, "status": status, **extra})


def _done_event(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: raw.get(k) for k in ("id", "summary", "day", "start_time", "minutes", "all_day", "link")}


def _line(e: dict[str, Any]) -> str:
    when = f"{e['day']} all day" if e.get("all_day") else f"{e['day']} {e['start_time']} ({e['minutes']} min)"
    return f"- id {e['id']} | {when} | {e['summary']}"


# ------------------------------------------------------------------------------ reading


async def _status(ctx: AgentContext) -> str:
    try:
        status = await ctx.gateway().status(ctx.user.id)
    except CalendarToolError as exc:
        raise _failure(ctx, exc) from exc
    if not status.get("connected"):
        ctx.emit({"type": "card", "kind": "calendar_connect", "data": {"reason": "not_connected"}})
        return "Google Calendar is not connected. The student can connect it on the Calendar page."
    if status.get("needs_reconnect"):
        ctx.emit({"type": "card", "kind": "calendar_connect", "data": {"reason": "reconnect"}})
        return "Google Calendar needs to be connected again on the Calendar page."
    return "Google Calendar is connected. Events are kept on a calendar named MindNest AI."


class ListArgs(BaseModel):
    start: date | None = Field(default=None, description="First day, YYYY-MM-DD. Default: today.")
    end: date | None = Field(default=None, description=f"Last day, YYYY-MM-DD, at most {MAX_DAYS} days after start. Default: 6 days after start.")


async def _list_events(ctx: AgentContext, start: date | None = None, end: date | None = None) -> str:
    first = start or _today(ctx)
    last = end or first + timedelta(days=6)
    if last < first or (last - first).days > MAX_DAYS:
        raise ToolFailure(f"The range must be between 1 and {MAX_DAYS} days.")
    await _require_calendar(ctx)
    try:
        events = await ctx.gateway().list_events(ctx.user.id, first.isoformat(), last.isoformat(), _zone(ctx), MAX_LISTED)
    except CalendarToolError as exc:
        raise _failure(ctx, exc) from exc
    ctx.emit({"type": "card", "kind": "calendar_events", "data": {
        "start": first.isoformat(), "end": last.isoformat(), "events": [_done_event(e) for e in events]}})
    if not events:
        return f"There are no events on the MindNest AI calendar from {first} to {last}. (Other Google calendars cannot be seen.)"
    note = f" Only the first {MAX_LISTED} are shown." if len(events) >= MAX_LISTED else ""
    return f"Events on the MindNest AI calendar from {first} to {last}:\n" + "\n".join(_line(e) for e in events) + note


# ------------------------------------------------------------------------------ changing


class AddArgs(BaseModel):
    summary: str = Field(description="The event title.", min_length=1, max_length=200)
    day: date = Field(description="The day, YYYY-MM-DD.")
    start_time: str = Field(default="", description="HH:MM on a 24-hour clock. Leave empty for an all-day event.", max_length=5)
    minutes: int = Field(default=60, ge=5, le=1440, description="Length in minutes (ignored for all-day events).")
    description: str = Field(default="", max_length=2000)


def _check_future(ctx: AgentContext, day: date) -> None:
    if day < _today(ctx):
        raise ToolFailure(f"{day} is in the past. Ask the student for a day from today ({_today(ctx)}) on.")


async def _add_event(
    ctx: AgentContext, summary: str, day: date, start_time: str = "", minutes: int = 60, description: str = ""
) -> str:
    try:
        event = EventIn(summary=summary, description=description, day=day, start_time=start_time,
                        minutes=minutes, timezone=_zone(ctx))
    except ValidationError as exc:
        raise _problem(exc) from exc
    _check_future(ctx, day)
    await _require_calendar(ctx)
    proposal_id = _proposal_id(ctx, "add", {"event": _shown(event)})
    proposal = {"proposal_id": proposal_id, "action": "add", "editable": True, "event": _shown(event)}
    approved, edits = _ask(ctx, "add_event", summary, proposal)
    if not approved:
        _settle(ctx, proposal_id, "rejected")
        return "The student declined, so NOTHING was added. Do not add it unless they ask again."
    try:
        final = apply_edits(event, edits)
        _check_future(ctx, final.day)
    except (ValidationError, ToolFailure) as exc:
        _settle(ctx, proposal_id, "failed", error="invalid_edit")
        raise (_problem(exc) if isinstance(exc, ValidationError) else exc) from exc
    try:
        made = await ctx.gateway().create_event(ctx.user.id, f"{ctx.run_id}:{proposal_id}", final)
    except CalendarToolError as exc:
        _settle(ctx, proposal_id, "failed", error=exc.code)
        raise _failure(ctx, exc) from exc
    _settle(ctx, proposal_id, "approved", event=_shown(final), result=_done_event(made))
    return f"The student approved and the event was ADDED to their Google Calendar: {_line(made)}"


class EventIdArgs(BaseModel):
    event_id: str = Field(description="The id of an event, from list_events.", min_length=1, max_length=200)


class MoveArgs(EventIdArgs):
    summary: str | None = Field(default=None, max_length=200, description="New title, only if it changes.")
    day: date | None = Field(default=None, description="New day, YYYY-MM-DD, only if it changes.")
    start_time: str | None = Field(default=None, max_length=8, description='New HH:MM, or "all-day" to make it an all-day event. Only if it changes.')
    minutes: int | None = Field(default=None, ge=5, le=1440, description="New length in minutes, only if it changes.")
    description: str | None = Field(default=None, max_length=2000)


def _from_google(ctx: AgentContext, raw: dict[str, Any]) -> EventIn:
    try:
        return EventIn(
            summary=raw["summary"] or "(no title)", description=raw.get("description", ""), day=raw["day"],
            start_time=raw.get("start_time", ""), minutes=raw.get("minutes") or 60,
            timezone=raw.get("timezone") or _zone(ctx), transparent=bool(raw.get("transparent")),
            source_type=raw.get("source_type", ""), source_id=raw.get("source_id", ""),
        )
    except (ValidationError, KeyError) as exc:
        raise ToolFailure("That event could not be read, so it cannot be changed from chat.") from exc


async def _current(ctx: AgentContext, event_id: str) -> dict[str, Any]:
    await _require_calendar(ctx)
    try:
        return await ctx.gateway().get_event(ctx.user.id, event_id)
    except CalendarToolError as exc:
        raise _failure(ctx, exc) from exc


async def _move_event(
    ctx: AgentContext, event_id: str, summary: str | None = None, day: date | None = None,
    start_time: str | None = None, minutes: int | None = None, description: str | None = None,
) -> str:
    if all(v is None for v in (summary, day, start_time, minutes, description)):
        raise ToolFailure("Nothing to change was given. Ask the student what should change.")
    raw = await _current(ctx, event_id)
    before = _from_google(ctx, raw)
    changes: dict[str, Any] = {k: v for k, v in
                               {"summary": summary, "day": day, "minutes": minutes, "description": description}.items()
                               if v is not None}
    if start_time is not None:
        changes["start_time"] = "" if start_time.strip().lower() in ("all-day", "all day", "allday", "") else start_time
    try:
        after = apply_edits(before, EventEdits.model_validate(changes))
    except ValidationError as exc:
        raise _problem(exc) from exc
    _check_future(ctx, after.day)
    proposal_id = _proposal_id(ctx, "move", {"id": event_id, "after": _shown(after)})
    proposal = {"proposal_id": proposal_id, "action": "move", "editable": True, "event_id": event_id,
                "before": _shown(before), "event": _shown(after)}
    approved, edits = _ask(ctx, "move_event", before.summary, proposal)
    if not approved:
        _settle(ctx, proposal_id, "rejected")
        return "The student declined, so NOTHING was changed. Do not change it unless they ask again."
    try:
        final = apply_edits(after, edits)
        _check_future(ctx, final.day)
    except (ValidationError, ToolFailure) as exc:
        _settle(ctx, proposal_id, "failed", error="invalid_edit")
        raise (_problem(exc) if isinstance(exc, ValidationError) else exc) from exc
    try:
        moved = await ctx.gateway().update_event(ctx.user.id, event_id, final)
    except CalendarToolError as exc:
        _settle(ctx, proposal_id, "failed", error=exc.code)
        raise _failure(ctx, exc) from exc
    result = {**_done_event(moved), "link": moved.get("link") or raw.get("link")}
    _settle(ctx, proposal_id, "approved", event=_shown(final), result=result)
    return f"The student approved and the event was UPDATED on their Google Calendar: {_line({**_shown(final), 'id': event_id})}"


async def _remove_event(ctx: AgentContext, event_id: str) -> str:
    raw = await _current(ctx, event_id)
    before = _from_google(ctx, raw)
    proposal_id = _proposal_id(ctx, "remove", {"id": event_id})
    proposal = {"proposal_id": proposal_id, "action": "remove", "editable": False, "event_id": event_id,
                "event": _shown(before)}
    approved, _ = _ask(ctx, "remove_event", before.summary, proposal)
    if not approved:
        _settle(ctx, proposal_id, "rejected")
        return "The student declined, so NOTHING was removed."
    try:
        await ctx.gateway().delete_event(ctx.user.id, event_id)
    except CalendarToolError as exc:
        _settle(ctx, proposal_id, "failed", error=exc.code)
        raise _failure(ctx, exc) from exc
    _settle(ctx, proposal_id, "approved", result={"id": event_id})
    return f"The student approved and the event '{before.summary}' was REMOVED from their Google Calendar."


def calendar_tools(ctx: AgentContext) -> list[Any]:
    return [
        agent_tool(ctx, "calendar", "calendar_status", "Check whether Google Calendar is connected.",
                   NoArgs, _status, lambda a: ""),
        agent_tool(ctx, "calendar", "list_events",
                   "List the events on the student's MindNest AI calendar in a date range (shows them as a card).",
                   ListArgs, _list_events, lambda a: " → ".join(str(x) for x in (a.get("start"), a.get("end")) if x)),
        agent_tool(ctx, "calendar", "add_event",
                   "Propose adding an event to the student's Google Calendar. Pauses for their approval.",
                   AddArgs, _add_event, lambda a: str(a.get("summary", "")), approval=True),
        agent_tool(ctx, "calendar", "move_event",
                   "Propose changing an event (day, time, length, title) on the student's Google Calendar. Pauses for their approval.",
                   MoveArgs, _move_event, lambda a: str(a.get("event_id", "")), approval=True),
        agent_tool(ctx, "calendar", "remove_event",
                   "Propose deleting an event from the student's Google Calendar. Pauses for their approval.",
                   EventIdArgs, _remove_event, lambda a: str(a.get("event_id", "")), approval=True),
    ]


async def prepare(
    ctx: AgentContext, step: PlanStep, results: list[dict[str, Any]], config: RunnableConfig
) -> Prepared:
    system = base_prompt(ctx, "calendar agent", ROLE.format(today=today_line(ctx)), earlier_work(results))
    return Prepared(system, [*chat_messages(ctx.history), HumanMessage(ctx.question)])


register(
    AgentSpec(
        "calendar", "calendar agent",
        "shows, adds, moves and removes events on the student's Google Calendar (asks them to approve "
        "every change). Use it for 'put X on my calendar', 'what is on my calendar', 'move/cancel my "
        "event'. Study tasks, exams and assignment dates belong to the planner.",
        prepare, calendar_tools,
    )
)
