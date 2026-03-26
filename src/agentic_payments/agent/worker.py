"""Worker behavior strategy — execute assigned tasks and request payment."""

from __future__ import annotations

import structlog

from agentic_payments.agent.executor import EchoExecutor, Executor
from agentic_payments.agent.strategy import StrategyContext
from agentic_payments.agent.task import TaskStatus

logger = structlog.get_logger(__name__)


class WorkerBehavior:
    """Strategy for worker agents: pick up assigned tasks, execute, submit results.

    Each tick:
    1. Find tasks assigned to this worker (status=ASSIGNED)
    2. If under capacity, move to EXECUTING and run executor
    3. On success, mark COMPLETED and request payment
    4. On failure, mark FAILED with error
    """

    def __init__(
        self,
        executor: Executor | None = None,
        max_concurrent: int = 5,
    ) -> None:
        self.executor: Executor = executor or EchoExecutor()
        self.max_concurrent = max_concurrent

    async def tick(self, ctx: StrategyContext) -> None:
        """Process assigned tasks up to max_concurrent per tick."""
        # Find tasks assigned to us
        assigned = [
            t
            for t in ctx.tasks.by_status(TaskStatus.ASSIGNED)
            if t.worker_peer_id == ctx.peer_id
        ]

        executed_this_tick = 0
        for task in assigned:
            if executed_this_tick >= self.max_concurrent:
                logger.debug(
                    "worker_at_capacity", executed=executed_this_tick, max=self.max_concurrent
                )
                break

            executed_this_tick += 1
            try:
                ctx.tasks.update_status(task.task_id, TaskStatus.EXECUTING)
                logger.info("worker_executing", task_id=task.task_id)

                result = await self.executor.execute(task)
                task.result = result
                ctx.tasks.update_status(task.task_id, TaskStatus.COMPLETED)
                logger.info("worker_completed", task_id=task.task_id)

                # Payment is handled by the coordinator — worker just logs completion
                if task.amount > 0:
                    logger.info(
                        "worker_awaiting_payment",
                        task_id=task.task_id,
                        amount=task.amount,
                    )
            except Exception as exc:
                task.error = str(exc)
                # Only transition to FAILED if still EXECUTING
                if task.status == TaskStatus.EXECUTING:
                    ctx.tasks.update_status(task.task_id, TaskStatus.FAILED)
                logger.warning("worker_task_failed", task_id=task.task_id, error=str(exc))
