"""
AI Task Queue — Redis-backed async task processing for AI/ML jobs.

Used for:
- Batch image analysis
- Bulk report processing
- Scheduled prediction jobs
- Model warmup tasks

Tasks are processed asynchronously. Results are stored in Redis
with TTL and can be retrieved by task_id.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from app.ai.providers.base import TaskType
from app.ai.router.model_router import get_model_router

logger = structlog.get_logger()

TASK_QUEUE_KEY = "ai:task_queue"
TASK_RESULT_PREFIX = "ai:task_result:"
TASK_TTL_SECONDS = 3600  # 1 hour


class AITaskQueue:
    """Redis-backed AI task queue."""

    async def enqueue(
        self,
        task_type: str,
        input_data: Any,
        *,
        priority: int = 5,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add a task to the queue. Returns task_id."""
        task_id = str(uuid.uuid4())
        task = {
            "task_id": task_id,
            "task_type": task_type,
            "input_data": input_data,
            "priority": priority,
            "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }

        try:
            from app.integrations import cache
            await cache.cache_set(
                f"ai:task:{task_id}",
                task,
                ttl=TASK_TTL_SECONDS,
            )
            logger.info("task_enqueued", task_id=task_id, task_type=task_type)
        except Exception as exc:
            logger.warning("task_enqueue_failed", task_id=task_id, error=str(exc))

        return task_id

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get task status and result."""
        try:
            from app.integrations import cache
            return await cache.cache_get(f"ai:task:{task_id}")
        except Exception as exc:
            logger.warning("task_get_failed", task_id=task_id, error=str(exc))
            return None

    async def process_task(self, task_id: str) -> dict[str, Any]:
        """Process a single task. Called by worker."""
        task = await self.get_task(task_id)
        if not task:
            return {"error": "Task not found", "task_id": task_id}

        try:
            task_type = task["task_type"]
            input_data = task["input_data"]

            # Update status
            task["status"] = "processing"
            task["started_at"] = datetime.now(timezone.utc).isoformat()
            await self._update_task(task)

            # Route to appropriate handler
            if task_type == "hazard_classification":
                result = await self._process_hazard_classification(input_data)
            elif task_type == "damage_assessment":
                result = await self._process_damage_assessment(input_data)
            elif task_type == "report_analysis":
                result = await self._process_report_analysis(input_data)
            else:
                result = {"error": f"Unknown task type: {task_type}"}

            # Update with result
            task["status"] = "completed"
            task["result"] = result
            task["completed_at"] = datetime.now(timezone.utc).isoformat()
            await self._update_task(task)

            logger.info("task_completed", task_id=task_id, task_type=task_type)
            return task

        except Exception as exc:
            logger.warning("task_processing_failed", task_id=task_id, error=str(exc))
            task["status"] = "failed"
            task["error"] = str(exc)
            task["completed_at"] = datetime.now(timezone.utc).isoformat()
            await self._update_task(task)
            return task

    async def _process_hazard_classification(self, input_data: Any) -> dict[str, Any]:
        router = get_model_router()
        result = await router.route(TaskType.HAZARD_CLASSIFICATION, input_data)
        return result.to_dict()

    async def _process_damage_assessment(self, input_data: Any) -> dict[str, Any]:
        router = get_model_router()
        result = await router.route(TaskType.DAMAGE_ASSESSMENT, input_data)
        return result.to_dict()

    async def _process_report_analysis(self, input_data: Any) -> dict[str, Any]:
        from app.ai.nlp.disaster_nlp import get_disaster_nlp
        nlp = get_disaster_nlp()
        text = input_data if isinstance(input_data, str) else input_data.get("text", "")
        return await nlp.analyze(text)

    async def _update_task(self, task: dict[str, Any]) -> None:
        try:
            from app.integrations import cache
            await cache.cache_set(
                f"ai:task:{task['task_id']}",
                task,
                ttl=TASK_TTL_SECONDS,
            )
        except Exception as exc:
            logger.warning("task_update_failed", task_id=task.get("task_id"), error=str(exc))


# Singleton
_queue: AITaskQueue | None = None


def get_task_queue() -> AITaskQueue:
    global _queue
    if _queue is None:
        _queue = AITaskQueue()
    return _queue
