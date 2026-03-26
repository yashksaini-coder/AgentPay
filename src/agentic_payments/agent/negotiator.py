"""Autonomous negotiation strategy — auto-accept/counter/reject offers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import structlog

from agentic_payments.agent.strategy import StrategyContext
from agentic_payments.agent.task import TaskStatus

logger = structlog.get_logger(__name__)


class NegotiationDecision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    COUNTER = "counter"


@dataclass
class NegotiationConfig:
    """Configuration for autonomous negotiation."""

    max_price: int = 0  # 0 = no limit (accept any price)
    min_trust_score: float = 0.0  # Minimum trust to engage
    auto_accept: bool = True  # Auto-accept if conditions met
    counter_offer_ratio: float = 0.8  # Counter at 80% of asking price


class AutonomousNegotiator:
    """Strategy that automatically handles incoming price quotes and work requests.

    Decision logic per tick:
    - Scans pending tasks where this node is the requester
    - For each, evaluates price and trust score of the worker
    - Accepts, rejects, or counters based on NegotiationConfig
    """

    MAX_DECISIONS = 200  # Cap decision log to prevent unbounded growth
    MAX_NEGOTIATION_ROUNDS = 10  # Max counter-offers per task before rejecting

    def __init__(self, config: NegotiationConfig | None = None) -> None:
        self.config = config or NegotiationConfig()
        self._decisions: list[dict] = []  # Log of recent decisions

    @property
    def recent_decisions(self) -> list[dict]:
        return list(self._decisions[-20:])

    def evaluate_offer(
        self,
        price: int,
        peer_id: str,
        ctx: StrategyContext,
    ) -> tuple[NegotiationDecision, int]:
        """Evaluate a price offer. Returns (decision, counter_price).

        counter_price is only meaningful when decision == COUNTER.
        """
        # Check trust
        trust = 1.0
        if ctx.reputation_tracker is not None:
            trust = ctx.reputation_tracker.get_trust_score(peer_id)

        if trust < self.config.min_trust_score:
            return NegotiationDecision.REJECT, 0

        # Check price
        price_ok = self.config.max_price == 0 or price <= self.config.max_price

        if price_ok and self.config.auto_accept:
            return NegotiationDecision.ACCEPT, 0

        if not price_ok:
            counter = int(price * self.config.counter_offer_ratio)
            return NegotiationDecision.COUNTER, counter

        return NegotiationDecision.ACCEPT, 0

    async def tick(self, ctx: StrategyContext) -> None:
        """Process pending tasks that need negotiation decisions."""
        # Only negotiate if role is unset or 'worker'
        if ctx.role is not None and ctx.role != "worker":
            return

        pending = ctx.tasks.pending_tasks()
        for task in pending:
            if not task.requester_peer_id or task.requester_peer_id == ctx.peer_id:
                # Tasks we created ourselves — skip negotiation
                continue

            decision, counter_price = self.evaluate_offer(
                price=task.amount,
                peer_id=task.requester_peer_id,
                ctx=ctx,
            )

            record = {
                "task_id": task.task_id,
                "peer_id": task.requester_peer_id,
                "price": task.amount,
                "decision": decision.value,
                "counter_price": counter_price,
            }
            self._decisions.append(record)
            # Cap decision log to prevent unbounded growth (issue #31)
            if len(self._decisions) > self.MAX_DECISIONS:
                self._decisions = self._decisions[-self.MAX_DECISIONS :]

            # Check if this task has exceeded max negotiation rounds
            task_rounds = sum(1 for d in self._decisions if d["task_id"] == task.task_id)
            if (
                task_rounds > self.MAX_NEGOTIATION_ROUNDS
                and decision == NegotiationDecision.COUNTER
            ):
                logger.info(
                    "negotiator_max_rounds_exceeded",
                    task_id=task.task_id,
                    rounds=task_rounds,
                )
                decision = NegotiationDecision.REJECT
                record["decision"] = decision.value

            if decision == NegotiationDecision.ACCEPT:
                logger.info(
                    "negotiator_accept",
                    task_id=task.task_id,
                    price=task.amount,
                    peer=task.requester_peer_id[:16],
                )
                ctx.tasks.update_status(task.task_id, TaskStatus.ASSIGNED)
                task.worker_peer_id = ctx.peer_id
            elif decision == NegotiationDecision.REJECT:
                logger.info(
                    "negotiator_reject",
                    task_id=task.task_id,
                    price=task.amount,
                    peer=task.requester_peer_id[:16],
                )
                ctx.tasks.update_status(task.task_id, TaskStatus.FAILED)
                task.error = (
                    "rejected: max negotiation rounds exceeded"
                    if task_rounds > self.MAX_NEGOTIATION_ROUNDS
                    else "rejected: trust too low"
                )
            else:
                logger.info(
                    "negotiator_counter",
                    task_id=task.task_id,
                    original=task.amount,
                    counter=counter_price,
                    peer=task.requester_peer_id[:16],
                )
                # Update task amount to counter-offer; stays PENDING for re-evaluation
                task.amount = counter_price
