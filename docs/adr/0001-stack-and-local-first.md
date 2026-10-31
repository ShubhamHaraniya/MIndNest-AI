# ADR 0001: Stack and local-first setup

Date: 2026-10-27. Status: accepted; partly updated by [ADR 0002](0002-agents-providers-and-evaluation.md)
(Anthropic is also a provider, chat runs on LangGraph agents, and evaluation tables live in `public`).

## Decisions

- **Backend:** FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic. Migrations are written in SQL.
- **Frontend:** Next.js (App Router), TypeScript, Tailwind with CSS-variable design tokens.
- **Data:** PostgreSQL 16 with pgvector and pg_trgm; Redis; S3-compatible storage (RustFS locally, because MinIO no longer publishes images).
- **Orchestration:** LangChain and LangGraph (Postgres checkpointer), LangSmith, MCP, Ragas.
  These are wired in during M3 and M4; M0 does not include them yet.
- **Generation:** bring-your-own-key only (OpenAI, Gemini, Groq). No local generation model.
- **Embeddings and reranking:** self-hosted BGE-M3 and bge-reranker-v2-m3 in a small HTTP
  service on the host GPU. The embedding column is `vector(1024)`; switching to a model with a
  different dimension needs a new migration and a re-embed.
- **Languages:** English, Hindi and Gujarati. Keyword search uses the `simple` text configuration
  and trigram matching because built-in stemmers do not cover Hindi or Gujarati.
- **Hosting:** Docker Compose on the developer laptop. The model service runs outside Docker.

## Tenancy

Every user-facing query runs inside `mindnest_core.db.user_session`, which sets a
transaction-local `app.user_id`. Row-level security policies on subjects, materials, chunks,
conversations and agent runs compare owners to that setting. The runtime role is not a table
owner and is not a superuser, so policies cannot be bypassed by application mistakes.
Evaluation data lives in a separate `eval` schema reachable only by its own role.

## Consequences

- A forgotten filter returns no rows instead of another user's rows.
- Workers must also open sessions with `user_session`, using the user id from the job payload.
- Institution and global sharing (Step 5) will extend the policies; until then everything is
  owner-only.
