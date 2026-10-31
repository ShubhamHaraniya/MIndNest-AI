"""The LangGraph that runs one student message.

    START -> router -> (one agent) -> (next agent, if the plan has two) -> END

Each agent is a small graph of its own:

    prepare -> model --(tool calls?)--> tools -> model ... -> finish

The router decides which agents run. Every agent has its own instructions and its own short list
of tools. Tools run as the signed-in student, so row-level security limits what they can touch.
"""

import operator
import time
from collections.abc import Hashable
from typing import Annotated, Any, TypedDict

from langchain_core.messages import (
    AnyMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
from mindnest_agents import runs
from mindnest_agents.errors import AgentError
from mindnest_agents.guardrails import Judge, refusal_text, tool_refusal

import mindnest_api.agent.agents  # noqa: F401  (registers the agents)
from mindnest_api.agent.context import AgentContext
from mindnest_api.agent.llmutil import ask, message_text, run_model
from mindnest_api.agent.registry import AGENTS, AgentSpec, agent_lines
from mindnest_api.agent.router import FALLBACK, PlanStep, decide
from mindnest_api.prompts import retrieval_query


class AgentState(TypedDict, total=False):
    plan: list[dict[str, str]]
    step_index: int
    system: str
    messages: Annotated[list[AnyMessage], add_messages]
    tool_rounds: int
    no_tools: bool
    results: Annotated[list[dict[str, Any]], operator.add]
    user_text: str  # the student's message, kept so the tool rails can compare against it
    blocked: bool  # the input rail stopped the message
    guard: dict[str, Any]  # what the input rail decided (labels only); visible in the LangSmith trace


def _edges(*names: str) -> dict[Hashable, str]:
    """Where a conditional edge may go: each name leads to the node of the same name."""
    return {n: n for n in names}


def _plan_step(state: AgentState) -> PlanStep:
    raw = state["plan"][state["step_index"]]
    return PlanStep(raw["agent"], raw.get("task", ""), raw.get("query", ""))


def make_judge(ctx: AgentContext, config: RunnableConfig) -> Judge | None:
    """The second opinion for risky messages: one short call to the student's own model. Provider
    problems are not the student's concern here, so they surface as "no opinion"."""
    if not ctx.settings.guardrails_judge:
        return None

    async def judge(system: str, message: str) -> str:
        try:
            return await ask(
                ctx, ctx.llm, [SystemMessage(system), HumanMessage(message)],
                {**config, "tags": [*config.get("tags", []), "guardrail"]},
            )
        except AgentError as exc:
            raise RuntimeError(exc.code) from exc

    return judge


def _agent_graph(ctx: AgentContext, spec: AgentSpec) -> Any:
    async def prepare(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        step = _plan_step(state)
        number = ctx.next_step()
        ctx.emit({"type": "step", "id": number, "agent": spec.name, "tool": None,
                  "summary": step.task[:200], "status": "done"})
        await ctx.record(node="agent", agent=spec.name, args={"task": step.task}, outcome="started")
        prepared = await spec.prepare(ctx, step, state.get("results", []), config)
        return {
            "system": prepared.system,
            "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *prepared.messages],
            "tool_rounds": 0,
            "no_tools": False,
        }

    async def model(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        tools = [] if state.get("no_tools") else spec.tools(ctx)
        llm = ctx.llm.bind_tools(tools) if tools else ctx.llm
        reply = await run_model(
            ctx, llm, [SystemMessage(state["system"]), *state["messages"]],
            {**config, "tags": [*config.get("tags", []), f"agent:{spec.name}"]},
        )
        return {"messages": [reply]}

    def after_model(state: AgentState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else "finish"

    async def _run_tool(tool: Any, call: dict[str, Any], by_name: dict[str, Any], state: AgentState, config: RunnableConfig) -> str:
        """One tool call, between the two tool rails: the call is checked before it runs (a change
        may not carry a link or an order that did not come from the student) and the result is made
        safe before the model reads it."""
        guard = ctx.guard
        if guard is not None:
            decision = await guard.check_tool_call(
                call["name"], call["args"], user_text=state.get("user_text") or ctx.question,
                allowed=set(by_name),
            )
            await ctx.note_guard(decision, tool=call["name"])
            if decision.blocked:
                return tool_refusal(decision.reasons)
        content = str(await tool.ainvoke(call["args"], config))
        if guard is not None and not content.startswith("ERROR:"):
            result = await guard.check_tool_result(
                call["name"], content, mask_optional=ctx.user.mask_personal_data
            )
            await ctx.note_guard(result, tool=call["name"])
            if result.action == "modify" and result.text is not None:
                content = result.text
        return content

    async def tools_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        last = state["messages"][-1]
        by_name = {tool.name: tool for tool in spec.tools(ctx)}
        rounds = state.get("tool_rounds", 0) + 1
        out: list[BaseMessage] = []
        calls = list(getattr(last, "tool_calls", None) or [])
        # A tool that needs the student's approval runs alone. Anything the model asked for in the
        # same round is not run (it could depend on the change, and the run may pause here).
        gated = next((c for c in calls if (getattr(by_name.get(c["name"]), "metadata", None) or {}).get("approval")), None)
        for call in calls:
            tool = by_name.get(call["name"])
            if tool is None:
                content = f"ERROR: there is no tool called {call['name']}."
            elif gated is not None and call is not gated:
                content = (
                    "ERROR: not run. A change that needs the student's approval is asked for on its own. "
                    "Ask for this again after that change has been decided."
                )
            else:
                content = await _run_tool(tool, call, by_name, state, config)
            out.append(ToolMessage(content=content, tool_call_id=call["id"], name=call["name"]))
        # When the budget is used up the next model turn gets no tools, so it must answer.
        spent = rounds >= ctx.settings.agent_max_tool_calls
        return {"messages": out, "tool_rounds": rounds, "no_tools": spent}

    async def finish(state: AgentState) -> dict[str, Any]:
        text = message_text(state["messages"][-1])
        step = _plan_step(state)
        index = state["step_index"] + 1
        if index < len(state["plan"]):  # another agent follows: keep the two answers apart
            ctx.emit({"type": "token", "text": "\n\n", "turn": ctx.next_turn()})
        return {"results": [{"agent": spec.name, "task": step.task, "text": text}], "step_index": index}

    graph = StateGraph(AgentState)
    graph.add_node("prepare", prepare)
    graph.add_node("model", model)
    graph.add_node("tools", tools_node)
    graph.add_node("finish", finish)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "model")
    graph.add_conditional_edges("model", after_model, {"tools": "tools", "finish": "finish"})
    graph.add_edge("tools", "model")
    graph.add_edge("finish", END)
    return graph.compile()


def build_graph(ctx: AgentContext, saver: BaseCheckpointSaver[Any] | None) -> Any:
    lines = agent_lines()
    allowed = set(AGENTS)

    async def guard_input(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        """The input rail. Rules decide almost every message; the student's own model is asked only
        when a message looks risky and might be innocent. A stopped message gets a short reply in
        the student's language and never reaches the router or an agent."""
        if ctx.guard is None:
            return {"blocked": False}
        decision = await ctx.guard.check_input(
            ctx.question, judge=make_judge(ctx, config), mask_optional=ctx.user.mask_personal_data
        )
        await ctx.note_guard(decision)
        if not decision.blocked:
            return {"blocked": False, "guard": decision.detail()}
        ctx.emit({"type": "token", "text": refusal_text(decision.code, ctx.question), "turn": ctx.next_turn()})
        return {"blocked": True, "plan": [], "step_index": 0, "guard": decision.detail()}

    def after_guard(state: AgentState) -> str:
        return END if state.get("blocked") else "router"

    async def router(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        started = time.perf_counter()
        previous_user = next((m.content for m in reversed(ctx.history) if m.role == "user"), None)
        plan = await decide(ctx, lines, allowed, retrieval_query(ctx.question, previous_user), config)
        plan.steps = [s for s in plan.steps if s.agent in AGENTS] or [PlanStep(FALLBACK)]
        ms = int((time.perf_counter() - started) * 1000)
        info = plan.as_dict()
        ctx.emit({"type": "route", "agents": [s.agent for s in plan.steps], "reason": plan.reason,
                  "shortcut": plan.shortcut, "ms": ms})
        await ctx.record(node="router", agent="router", args=info, outcome=",".join(s.agent for s in plan.steps), ms=ms)
        try:
            async with ctx.db.session() as session:
                await runs.set_route(session, ctx.run_id, info)
        except Exception:
            pass
        return {"plan": [s.as_dict() for s in plan.steps], "step_index": 0}

    def next_agent(state: AgentState) -> str:
        index = state.get("step_index", 0)
        plan = state.get("plan", [])
        return plan[index]["agent"] if index < len(plan) else END

    parent = StateGraph(AgentState)
    parent.add_node("guard_input", guard_input)
    parent.add_node("router", router)
    for name, spec in AGENTS.items():
        parent.add_node(name, _agent_graph(ctx, spec))
        parent.add_conditional_edges(name, next_agent, _edges(END, *AGENTS))
    parent.add_edge(START, "guard_input")
    parent.add_conditional_edges("guard_input", after_guard, _edges("router", END))
    parent.add_conditional_edges("router", next_agent, _edges(END, *AGENTS))
    return parent.compile(checkpointer=saver)
