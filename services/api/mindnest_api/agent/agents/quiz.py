"""The Quiz agent: makes quizzes from a subject and topic, with or without the student's notes.

A quiz about a topic the student's notes cover is built from those notes. A quiz about anything
else is written from the AI's general knowledge and labelled "not from your notes" everywhere it is
shown. The agent only starts the job: the questions are written in the background by the same
worker as quizzes made on the Quizzes page, and the student sees a card that fills in when ready."""

import json
import re
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from mindnest_core.quizlogic import DIFFICULTIES, MAX_QUESTIONS, MIN_QUESTIONS, QUESTION_TYPES, looks_like_prose
from pydantic import BaseModel, Field
from sqlalchemy import text

from mindnest_api.agent.agents.common import NoArgs, list_subjects_tool, today_line
from mindnest_api.agent.context import AgentContext
from mindnest_api.agent.registry import AgentSpec, Prepared, base_prompt, chat_messages, earlier_work, register
from mindnest_api.agent.router import PlanStep
from mindnest_api.agent.tools import ToolFailure, agent_tool, via_route
from mindnest_api.llm import PROVIDERS
from mindnest_api.retrieval import retrieve
from mindnest_api.routes import quizzes as quiz_routes

ROLE = """You make quizzes for the student and help them practise.

- When the student asks for a quiz, test, MCQs or practice questions, call create_quiz. Take the \\
subject and topic from their message. The topic can be anything ("process scheduling", "the French \\
Revolution"); the subject can be one of their subjects or just a name.
- If the chat is focused on a subject you may leave subject out. If neither the message nor the chat \\
names a subject or a topic, ask ONE short question about what the quiz should cover.
- Do not ask about the number of questions, difficulty or question types unless the student cares: \\
the defaults are fine (10 questions, medium, a mix).
- A quiz is based on the student's notes when their notes cover the topic, and otherwise on general \\
knowledge. After create_quiz, say in one or two sentences what you made and how many questions, and \\
state clearly which it is: "based on your notes" or "from general knowledge, not from your notes". \\
The questions are written in the background; a card with a Start button appears for the student.
- To go through cards that are due for spaced revision use start_revision. To show how earlier \\
quizzes went use list_quizzes. To open a quiz that is ready use start_quiz.
- Never invent a quiz id: use the ids from tool results.
- {today}"""

_WORD = re.compile(r"[\wऀ-ॿ઀-૿]{3,}", re.UNICODE)
_STOP = frozenset(
    "the and for with from that this what about into over under are was were has have how why when "
    "who which topic chapter unit lecture notes".split()
)
MIN_NOTES_PASSAGES = 3


def topic_words(topic: str) -> set[str]:
    return {w for w in (m.casefold() for m in _WORD.findall(topic)) if w not in _STOP}


def covers_topic(passage_text: str, words: set[str]) -> bool:
    """True if the passage mentions at least one significant word of the topic."""
    if not words:
        return True
    lowered = passage_text.casefold()
    return any(word in lowered for word in words)


def _all_types() -> list[Literal["mcq", "true_false", "short"]]:
    return ["mcq", "true_false", "short"]


class CreateQuizArgs(BaseModel):
    subject: str | None = Field(
        default=None,
        description="Subject name, ideally one of the student's subjects. Leave out to use the chat's subject.",
        max_length=150,
    )
    topic: str | None = Field(default=None, description="The topic to ask about, as the student said it.", max_length=200)
    count: int = Field(default=10, ge=MIN_QUESTIONS, le=MAX_QUESTIONS)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    types: list[Literal["mcq", "true_false", "short"]] = Field(default_factory=_all_types, min_length=1)
    language: Literal["en", "hi", "gu"] | None = Field(default=None, description="Only if the student asked for a language.")
    use_notes: Literal["auto", "yes", "no"] = Field(
        default="auto",
        description="auto: use the student's notes if they cover the topic. yes: only notes. no: general knowledge.",
    )


async def _create_quiz(
    ctx: AgentContext, subject: str | None = None, topic: str | None = None, count: int = 10,
    difficulty: str = "medium", types: list[str] | None = None, language: str | None = None,
    use_notes: str = "auto",
) -> str:
    subject = (subject or "").strip() or None
    topic = (topic or "").strip() or None
    found = ctx.find_subject(subject) if subject else None
    if subject and found is None and use_notes == "yes":
        raise ToolFailure(
            f"No subject of the student's matches '{subject}', so there are no notes to use. "
            f"Their subjects are: {ctx.subject_names()}."
        )
    if found is None and not subject and ctx.subject_id:
        found = next((s for s in ctx.subjects if s.id == ctx.subject_id), None)
    if not (found or subject or topic):
        raise ToolFailure("Neither a subject nor a topic was given. Ask the student what the quiz should cover.")
    subject_name = found.name if found else (subject or topic or "")
    kinds = [t for t in dict.fromkeys(types or QUESTION_TYPES) if t in QUESTION_TYPES]
    if not kinds or difficulty not in DIFFICULTIES:
        raise ToolFailure("Unknown question type or difficulty.")

    # --- notes or general knowledge ------------------------------------------------------------
    basis = "general"
    chunk_ids: list[str] = []
    note = ""
    if use_notes != "no" and found is not None and found.ready_materials > 0:
        if topic:
            async with ctx.db.session() as session:
                result = await retrieve(
                    session, ctx.models, f"{topic} {subject_name}", subject_id=found.id,
                    candidates=ctx.settings.retrieval_candidates, top_k=30,
                )
            words = topic_words(topic)
            usable = [p for p in result.passages if looks_like_prose(p.text) and covers_topic(p.text, words)]
            if len(usable) >= MIN_NOTES_PASSAGES or (use_notes == "yes" and usable):
                basis = "notes"
                chunk_ids = [str(p.chunk_id) for p in usable]
            elif use_notes == "yes":
                raise ToolFailure(f"The student's {subject_name} notes do not seem to cover '{topic}'.")
            else:
                note = f"The notes in {subject_name} do not seem to cover this topic, so it is from general knowledge."
        else:
            basis = "notes"  # a whole-subject quiz from a spread of their notes
    elif use_notes == "yes":
        raise ToolFailure("The student has no processed notes to base the quiz on.")

    chosen_language = language or ctx.user.answer_language or ctx.user.ui_language
    title = (f"{topic} ({subject_name})" if topic and subject_name != topic else topic or f"{subject_name} quiz")[:120]
    config: dict[str, Any] = {
        "count": count, "types": kinds, "difficulty": difficulty, "provider": ctx.provider,
        "model": ctx.model or PROVIDERS[ctx.provider].default_model, "basis": basis,
        "topic": topic, "subject_name": subject_name, "origin": "chat",
    }
    if chunk_ids:
        config["chunk_ids"] = chunk_ids
    async with ctx.db.session() as session:
        quiz_id = (
            await session.execute(
                text(
                    "INSERT INTO quizzes (user_id, subject_id, title, language, config) "
                    "VALUES (:u, :s, :t, :l, CAST(:c AS jsonb)) RETURNING id"
                ),
                {"u": ctx.user.id, "s": found.id if found else None, "t": title,
                 "l": chosen_language, "c": json.dumps(config, ensure_ascii=False)},
            )
        ).scalar_one()
    # Enqueued after the commit, so the worker can always see the row.
    await ctx.queue.enqueue_quiz_generation(quiz_id, ctx.user.id)
    ctx.emit({"type": "card", "kind": "quiz", "data": {
        "quiz_id": str(quiz_id), "title": title, "basis": basis, "count": count,
        "topic": topic, "subject": subject_name,
    }})
    where = "the student's notes" if basis == "notes" else "general knowledge (NOT the student's notes)"
    return (
        f"Quiz created: id {quiz_id}, '{title}', {count} questions, based on {where}. {note} "
        "The questions are being written in the background; a card with a Start button is "
        "already shown to the student."
    )


class QuizIdArgs(BaseModel):
    quiz_id: str = Field(description="The id of a quiz, from a tool result.")


async def _start_quiz(ctx: AgentContext, quiz_id: str) -> str:
    try:
        from uuid import UUID

        qid = UUID(quiz_id)
    except ValueError as exc:
        raise ToolFailure("That is not a valid quiz id.") from exc
    started = await via_route(quiz_routes.start_attempt(qid, ctx.user, ctx.db))
    ctx.emit({"type": "card", "kind": "quiz_attempt", "data": {
        "quiz_id": str(qid), "attempt_id": str(started.id)}})
    return f"Attempt {started.id} is open. The student can answer the questions from the card."


async def _list_quizzes(ctx: AgentContext) -> str:
    quizzes = await via_route(quiz_routes.list_quizzes(ctx.user, ctx.db))
    if not quizzes:
        return "The student has no quizzes yet."
    lines = []
    for q in quizzes[:15]:
        last = f", last score {round(q.last_attempt.percent * 100)}%" if q.last_attempt and q.last_attempt.percent is not None else ""
        lines.append(f"- id {q.id} | {q.title} | {q.status} | {q.question_count} questions{last}")
    return "\n".join(lines)


class RevisionArgs(BaseModel):
    count: int = Field(default=10, ge=1, le=MAX_QUESTIONS)
    subject: str | None = Field(default=None, description="Only cards from this subject.")


async def _start_revision(ctx: AgentContext, count: int = 10, subject: str | None = None) -> str:
    sid = None
    if subject:
        found = ctx.find_subject(subject)
        if found is None:
            raise ToolFailure(f"No subject matches '{subject}'. Their subjects are: {ctx.subject_names()}.")
        sid = found.id
    quiz = await via_route(quiz_routes.start_revision(quiz_routes.RevisionIn(count=count, subject_id=sid), ctx.user, ctx.db))
    ctx.emit({"type": "card", "kind": "quiz", "data": {
        "quiz_id": str(quiz.id), "title": quiz.title, "basis": "revision", "count": quiz.question_count,
        "topic": None, "subject": quiz.subject_name}})
    return f"A revision quiz with {quiz.question_count} due cards is ready (id {quiz.id}); a card with a Start button is shown."


def quiz_tools(ctx: AgentContext) -> list[Any]:
    return [
        agent_tool(
            ctx, "quiz", "create_quiz",
            "Create a quiz about a subject and/or topic. Uses the student's notes when they cover the "
            "topic, otherwise the AI's general knowledge. Returns at once; the questions are written in the background.",
            CreateQuizArgs, _create_quiz, lambda a: " · ".join(x for x in (a.get("topic"), a.get("subject")) if x),
        ),
        agent_tool(ctx, "quiz", "start_quiz", "Open an attempt at a quiz that is ready.",
                   QuizIdArgs, _start_quiz, lambda a: a.get("quiz_id", "")),
        agent_tool(ctx, "quiz", "list_quizzes", "List the student's recent quizzes with their last scores.",
                   NoArgs, _list_quizzes, lambda a: ""),
        agent_tool(ctx, "quiz", "start_revision", "Make a revision quiz from the flashcards that are due today.",
                   RevisionArgs, _start_revision, lambda a: a.get("subject") or ""),
        list_subjects_tool(ctx, "quiz"),
    ]


async def prepare(
    ctx: AgentContext, step: PlanStep, results: list[dict[str, Any]], config: RunnableConfig
) -> Prepared:
    system = base_prompt(ctx, "quiz agent", ROLE.format(today=today_line(ctx)),
                         f"\nThe student's subjects: {ctx.subject_names()}." + earlier_work(results))
    return Prepared(system, [*chat_messages(ctx.history), HumanMessage(ctx.question)])


register(
    AgentSpec(
        "quiz", "quiz agent",
        "makes quizzes, tests, MCQs and practice questions on a subject and/or topic (from the "
        "student's notes when they cover it, otherwise from general knowledge), starts revision of "
        "due flashcards, and shows quiz results.",
        prepare, quiz_tools,
    )
)
