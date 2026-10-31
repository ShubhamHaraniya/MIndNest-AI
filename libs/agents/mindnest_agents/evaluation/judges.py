"""Scores that need a language model, computed with Ragas.

faithfulness       Ragas Faithfulness: the answer is split into claims and each claim is checked
                   against the passages the agent was shown (1.0 = every claim is supported)
topic adherence    Ragas AspectCritic with a short definition of what a study assistant is for

The model that judges is chosen separately from the model that is being tested: judging an answer
with the same small model that wrote it flatters it. Ragas is an optional install (`pip install
-e ".[eval]"`); without it these scores are simply left out of the report."""

import asyncio
import logging
import warnings
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger("mindnest.eval")

TOPIC_DEFINITION = (
    "The response stays within what a study assistant for college students is for: explaining course "
    "material, quizzes and revision, study plans, assignments, and organising study time. If the "
    "request is outside that (for example cooking, sports, shopping or personal advice), a good "
    "response politely says it is outside what it helps with here and offers a study-related "
    "alternative, instead of fully carrying out the unrelated task. Answer 1 if the response stays "
    "within that scope. Answer 0 if it fully does the unrelated task."
)


class RagasMissing(RuntimeError):
    pass


class RagasJudge:
    def __init__(self, llm: BaseChatModel, *, concurrency: int = 2) -> None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from ragas.llms import LangchainLLMWrapper
                from ragas.metrics import AspectCritic, Faithfulness
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RagasMissing(
                'Ragas is not installed. Run: pip install -e ".[eval]"'
            ) from exc
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wrapped: Any = LangchainLLMWrapper(llm)
            self._faithfulness = Faithfulness(llm=wrapped)
            self._topic = AspectCritic(name="study_scope", definition=TOPIC_DEFINITION, llm=wrapped)
        self._gate = asyncio.Semaphore(concurrency)

    async def faithfulness(self, question: str, answer: str, contexts: list[str]) -> float | None:
        if not answer.strip() or not contexts:
            return None
        from ragas.dataset_schema import SingleTurnSample

        sample = SingleTurnSample(user_input=question, response=answer, retrieved_contexts=contexts)
        async with self._gate:
            score = await self._faithfulness.single_turn_ascore(sample)
        return None if score is None or score != score else float(score)

    async def topic_adherence(self, question: str, answer: str) -> float | None:
        if not answer.strip():
            return None
        from ragas.dataset_schema import SingleTurnSample

        sample = SingleTurnSample(user_input=question, response=answer)
        async with self._gate:
            score = await self._topic.single_turn_ascore(sample)
        return None if score is None or score != score else float(score)


async def score_results(results: list[Any], judge: RagasJudge) -> None:
    """Fill in `faithfulness` and `topic` on the results that call for them. A judge failure on one
    case is recorded on that case and never stops the run."""

    async def one(result: Any) -> None:
        rec, exp = result.record, result.case.expect
        if rec.status != "ok":
            return
        try:
            if exp.get("grounded") and rec.sources:
                contexts = [str(s.get("snippet", "")) for s in rec.sources if s.get("snippet")]
                result.faithfulness = await judge.faithfulness(result.case.message, rec.answer, contexts)
            if exp.get("on_topic") is False:
                result.topic = await judge.topic_adherence(result.case.message, rec.answer)
        except Exception as exc:
            result.judge_error = f"{type(exc).__name__}"
            logger.warning("judge failed for %s: %s", result.case.id, type(exc).__name__)

    await asyncio.gather(*(one(r) for r in results))
