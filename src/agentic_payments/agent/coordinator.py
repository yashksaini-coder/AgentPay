"""Coordinator behavior strategy — assign tasks to workers and settle payments."""

from __future__ import annotations

import structlog

from agentic_payments.agent.strategy import StrategyContext
from agentic_payments.agent.task import TaskStatus

logger = structlog.get_logger(__name__)


class CoordinatorBehavior:
    """Strategy for coordinator agents: distribute tasks to workers, collect results, pay.

    Each tick:
    1. Find PENDING tasks (submitted by external clients)
    2. Select best available workers by reputation
    3. Assign tasks to workers
    4. For COMPLETED tasks, settle payment and mark PAID
    """

    def __init__(self, max_workers_per_round: int = 10) -> None:
        self.max_workers_per_round = max_workers_per_round

    def _select_worker(self, ctx: StrategyContext) -> str | None:
        """Pick the best available worker peer by trust score."""
        if not ctx.known_peers:
            return None

        if ctx.reputation_tracker is None:
            # No reputation data — pick first peer that isn't us
            for p in ctx.known_peers:
                if p != ctx.peer_id:
                    return p
            return None

        # Sort peers by trust score descending, exclude self
        candidates = [
            (p, ctx.reputation_tracker.get_trust_score(p))
            for p in ctx.known_peers
            if p != ctx.peer_id
        ]
        if not candidates:
            return None

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    async def tick(self, ctx: StrategyContext) -> None:
        """Assign pending tasks and settle completed ones."""
        # Only process if role is 'coordinator'
        if ctx.role is None or ctx.role != "coordinator":
            return

        # --- Assign pending tasks to workers ---
        pending = ctx.tasks.pending_tasks()
        for task in pending:
            worker = self._select_worker(ctx)
            if worker is None:
                logger.debug("coordinator_no_workers", task_id=task.task_id)
                break

            ctx.tasks.update_status(task.task_id, TaskStatus.ASSIGNED)
            task.worker_peer_id = worker
            logger.info(
                "coordinator_assigned",
                task_id=task.task_id,
                worker=worker[:16],
            )

            # Broadcast assignment if possible
            if ctx.broadcast:
                try:
                    await ctx.broadcast({
                        "type": "task_assignment",
                        "task_id": task.task_id,
                        "description": task.description,
                        "worker_peer_id": worker,
                        "amount": task.amount,
                    })
                except Exception as exc:
                    logger.warning("coordinator_broadcast_failed", error=str(exc))

        # --- Settle payments for completed tasks ---
        completed = ctx.tasks.by_status(TaskStatus.COMPLETED)
        for task in completed:
            if task.amount > 0 and task.worker_peer_id and ctx.send_payment:
                try:
                    await ctx.send_payment(
                        peer_id=task.worker_peer_id,
                        amount=task.amount,
                        task_id=task.task_id,
                    )
                    ctx.tasks.update_status(task.task_id, TaskStatus.PAID)
                    logger.info(
                        "coordinator_paid",
                        task_id=task.task_id,
                        worker=task.worker_peer_id[:16],
                        amount=task.amount,
                    )
                except Exception as exc:
                    logger.warning(
                        "coordinator_payment_failed",
                        task_id=task.task_id,
                        error=str(exc),
                    )
            else:
                # No payment needed — mark paid directly
                ctx.tasks.update_status(task.task_id, TaskStatus.PAID)
                logger.info("coordinator_settled_free", task_id=task.task_id)
