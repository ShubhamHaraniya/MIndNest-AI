# ADR 0002: Agent layer, four providers, and where evaluation data lives

Date: 2026-10-31. Status: accepted. Updates [ADR 0001](0001-stack-and-local-first.md); where the
two differ, this one describes the code as it is.

## What changed since ADR 0001

- **Four providers, not three.** Students bring their own key for Anthropic, Google Gemini, OpenAI
  or Groq. The list lives in `services/api/mindnest_api/llm.py` (`PROVIDERS`); students may also
  type any model name their provider accepts.
- **Chat runs on a LangGraph agent graph** (`services/api/mindnest_api/agent/graph.py`), not on a
  single prompt. A router picks up to two of seven agents (study, quiz, materials, planner,
  assignment, calendar, direct); each agent is a small sub-graph with its own tools. See
  [docs/agents.md](../agents.md) and the "Agents" chapter of [DOC.md](../../DOC.md).
- **Google Calendar is reached only through an MCP server** (`services/calendar_mcp`). The API
  never holds a calendar client; it mints a short-lived HMAC token that names the user, the tool
  and a hash of the arguments.
- **NeMo Guardrails** screen the student's input, every tool call and result, and the final
  output, on top of the pattern-based safety layer in `mindnest_core.aisafety`.
- **Evaluation tables are in the `public` schema with row-level security** (migration 0004), owned
  per student like everything else. The separate `eval` schema and the `mindnest_eval` role that
  ADR 0001 describes still exist but nothing writes to them.

## Why

- Agents let one message be a quiz request *and* a calendar request without a tangle of
  `if/else` in the chat route, and make every tool call visible to the student as a step.
- Routing every external side effect through MCP plus approval pauses means the model can propose
  a calendar change but cannot make one on its own.
- Keeping evaluation rows under ordinary row-level security means a student only ever sees their
  own datasets and runs, with no second access model to reason about.

## Consequences

- Every new agent is one module under `agent/agents/` plus one `register(...)` call.
- A tool that changes something outside MindNest must set `approval=True` so the graph pauses
  for the student's decision.
- Any new student-owned table needs a migration with `ENABLE ROW LEVEL SECURITY`, a policy keyed
  to `app.user_id`. Grants to `mindnest_app` are automatic (default privileges set in migration 0001).
