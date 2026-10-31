# Evaluating the agents

The tool scores the agents with a fixed set of test messages (`evals/agents/agent_v1.jsonl`, 53
cases: study, direct, quiz, materials, planner, assignment, calendar, routing, off_topic,
guardrail). Run it after changing a prompt, the router, a tool or a guardrail rule.

## 1. Offline (no model, no server, free)

```
pip install -e ".[dev]"
python -m mindnest_agents.evaluation offline
```

Checks the 16 cases marked `"offline": true` against the guardrails only. Prints a report and writes
it under `evals/reports/`. It should show every case passed, attack recall 100% and false-block
rate 0%. The same suite runs in `pytest libs/agents/tests/test_evaluation.py`.

## 2. Live (the real API and a real model)

1. Start the stack (`docker compose up -d --build`) and make a **separate test account**. Do not use
   your own: the run creates a subject, uploads two small notes and, with `--allow-writes`, adds
   planner items and quizzes. It removes what it made when it finishes.
2. In that account's Settings, add a provider key and choose a model. Optionally connect Google
   Calendar to include the calendar cases (they are skipped otherwise).
3. Install the extra scorers: `pip install -e ".[eval]"` (Ragas; it pins `langchain-community` below
   0.4 because Ragas 0.4 cannot import the newer one).
4. Run:

```
export EVAL_EMAIL=test-student@example.com
export EVAL_PASSWORD=...
export EVAL_JUDGE_API_KEY=...        # key for the model that SCORES answers
python -m mindnest_agents.evaluation live \
    --api-url http://localhost:3000/api/v1 \
    --judge-provider openai --judge-model gpt-4o-mini \
    --delay 4
```

Add `--allow-writes` to include planner/quiz cases, `--category study` or `--only study-calvin` to
run part of the set, `--limit 5` for a quick try, and `--langsmith` (with `LANGSMITH_API_KEY`) to
attach the scores to the traces. Chat is rate limited (20 per minute by default), so keep `--delay`
at 3 seconds or more (the default is 4); a 429 is retried automatically.

Use a different model as the judge from the one under test; a model scoring its own answers is too
kind. Without `--judge-*` the Ragas scores (groundedness, topic) are left out and everything else
still runs.

## Reading the report

Headline scores first, then a table of every case with the reason it failed. Groundedness is
measured against the 500-character source snippets the chat returns, not the whole chunk, so a
true answer can score low when the support sits just outside the snippet; look at the failing
cases before trusting a drop. Cost is tokens from the final `done` event.

## Adding a case

One JSON object per line. Everything under `expect` is optional.

```
{"id": "route-quiz-1", "category": "routing", "message": "Make me a quiz on cells",
 "writes": true, "expect": {"agents": ["quiz"], "tools": ["create_quiz"], "cards": ["quiz"]}}
```

Keys: `agents`, `tools`, `forbid_tools`, `cards`, `answer_any`, `answer_all`, `answer_none`, `guard`
(`block` / `allow`: did the input rail stop the message), `guard_offline`, `awaiting_approval`, `grounded`, `cites`,
`on_topic`, `max_ms`, `error`. Case flags: `offline`, `writes`, `subject`, `requires: ["google"]`.
The loader rejects unknown keys. Keep cases small and specific: one thing each.
