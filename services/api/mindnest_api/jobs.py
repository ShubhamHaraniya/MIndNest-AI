"""Handing work to the Celery worker."""

import asyncio
from typing import Protocol
from uuid import UUID


class IngestQueue(Protocol):
    async def enqueue_ingestion(self, material_id: UUID, owner_id: UUID) -> None: ...

    async def enqueue_evaluation(self, run_id: UUID, owner_id: UUID) -> None: ...

    async def enqueue_quiz_generation(self, quiz_id: UUID, owner_id: UUID) -> None: ...

    async def enqueue_attempt_grading(self, attempt_id: UUID, owner_id: UUID) -> None: ...

    async def enqueue_assignment_run(self, run_id: UUID, owner_id: UUID) -> None: ...

    async def enqueue_chat_attachment(self, attachment_id: UUID, owner_id: UUID) -> None: ...


class CeleryQueue:
    async def enqueue_ingestion(self, material_id: UUID, owner_id: UUID) -> None:
        from mindnest_worker.app import celery_app

        # send_task blocks on Redis, so keep it off the event loop.
        await asyncio.to_thread(
            celery_app.send_task,
            "mindnest.ingest_material",
            args=[str(material_id), str(owner_id)],
        )

    async def enqueue_evaluation(self, run_id: UUID, owner_id: UUID) -> None:
        from mindnest_worker.app import celery_app

        await asyncio.to_thread(
            celery_app.send_task,
            "mindnest.run_evaluation",
            args=[str(run_id), str(owner_id)],
            # Their own queue and worker (one run at a time) so that runs do not hit the
            # student's provider limits together and do not hold up ingestion.
            queue="eval",
        )

    async def enqueue_quiz_generation(self, quiz_id: UUID, owner_id: UUID) -> None:
        from mindnest_worker.app import celery_app

        await asyncio.to_thread(
            celery_app.send_task,
            "mindnest.generate_quiz",
            args=[str(quiz_id), str(owner_id)],
        )

    async def enqueue_attempt_grading(self, attempt_id: UUID, owner_id: UUID) -> None:
        from mindnest_worker.app import celery_app

        await asyncio.to_thread(
            celery_app.send_task,
            "mindnest.grade_attempt",
            args=[str(attempt_id), str(owner_id)],
        )

    async def enqueue_assignment_run(self, run_id: UUID, owner_id: UUID) -> None:
        from mindnest_worker.app import celery_app

        await asyncio.to_thread(
            celery_app.send_task,
            "mindnest.assignment_help",
            args=[str(run_id), str(owner_id)],
        )

    async def enqueue_chat_attachment(self, attachment_id: UUID, owner_id: UUID) -> None:
        from mindnest_worker.app import celery_app

        await asyncio.to_thread(
            celery_app.send_task,
            "mindnest.read_chat_attachment",
            args=[str(attachment_id), str(owner_id)],
        )
