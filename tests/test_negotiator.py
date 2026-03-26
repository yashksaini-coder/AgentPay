"""Tests for AutonomousNegotiator strategy."""

from __future__ import annotations

from agentic_payments.agent.negotiator import (
    AutonomousNegotiator,
    NegotiationConfig,
    NegotiationDecision,
)
from agentic_payments.agent.strategy import StrategyContext
from agentic_payments.agent.task import AgentTask, TaskStatus, TaskStore


class _MockReputation:
    """Minimal reputation tracker for tests."""

    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self._scores = scores or {}

    def get_trust_score(self, peer_id: str) -> float:
        return self._scores.get(peer_id, 0.5)


def _make_ctx(
    store: TaskStore,
    peer_id: str = "QmLocal",
    reputation: _MockReputation | None = None,
) -> StrategyContext:
    return StrategyContext(
        peer_id=peer_id,
        eth_address="0x0",
        channels=[],
        known_peers=[],
        tasks=store,
        gateway=None,
        reputation_tracker=reputation,
        role=None,
    )


class TestEvaluateOffer:
    def test_accept_within_budget(self):
        """Should accept if price <= max_price and trust >= min."""
        neg = AutonomousNegotiator(NegotiationConfig(max_price=1000, min_trust_score=0.3))
        ctx = _make_ctx(TaskStore(), reputation=_MockReputation({"peer-A": 0.8}))
        decision, _ = neg.evaluate_offer(price=500, peer_id="peer-A", ctx=ctx)
        assert decision == NegotiationDecision.ACCEPT

    def test_reject_low_trust(self):
        """Should reject if trust < min_trust_score."""
        neg = AutonomousNegotiator(NegotiationConfig(min_trust_score=0.9))
        ctx = _make_ctx(TaskStore(), reputation=_MockReputation({"peer-A": 0.1}))
        decision, _ = neg.evaluate_offer(price=100, peer_id="peer-A", ctx=ctx)
        assert decision == NegotiationDecision.REJECT

    def test_counter_over_budget(self):
        """Should counter at ratio when price > max_price."""
        neg = AutonomousNegotiator(NegotiationConfig(max_price=500, counter_offer_ratio=0.6))
        ctx = _make_ctx(TaskStore(), reputation=_MockReputation({"peer-A": 0.8}))
        decision, counter = neg.evaluate_offer(price=1000, peer_id="peer-A", ctx=ctx)
        assert decision == NegotiationDecision.COUNTER
        assert counter == 600

    def test_unlimited_max_price(self):
        """max_price=0 means no limit — always accept if trust OK."""
        neg = AutonomousNegotiator(NegotiationConfig(max_price=0, min_trust_score=0.0))
        ctx = _make_ctx(TaskStore(), reputation=_MockReputation({"peer-A": 0.5}))
        decision, _ = neg.evaluate_offer(price=999999, peer_id="peer-A", ctx=ctx)
        assert decision == NegotiationDecision.ACCEPT

    def test_no_reputation_tracker(self):
        """With no reputation tracker, trust defaults to 1.0 (permissive)."""
        neg = AutonomousNegotiator(NegotiationConfig(max_price=100, min_trust_score=0.5))
        ctx = _make_ctx(TaskStore(), reputation=None)
        decision, _ = neg.evaluate_offer(price=50, peer_id="peer-A", ctx=ctx)
        assert decision == NegotiationDecision.ACCEPT


class TestNegotiatorTick:
    async def test_accept_assigns_task(self):
        """Negotiator tick should assign accepted tasks."""
        store = TaskStore()
        store.add(
            AgentTask(
                task_id="t1",
                description="work",
                requester_peer_id="peer-A",
                amount=100,
            )
        )
        neg = AutonomousNegotiator(NegotiationConfig(max_price=200))
        ctx = _make_ctx(store, peer_id="QmLocal", reputation=_MockReputation({"peer-A": 0.8}))
        await neg.tick(ctx)
        assert store.get("t1").status == TaskStatus.ASSIGNED
        assert store.get("t1").worker_peer_id == "QmLocal"

    async def test_reject_fails_task(self):
        """Negotiator tick should fail rejected tasks."""
        store = TaskStore()
        store.add(
            AgentTask(
                task_id="t1",
                description="work",
                requester_peer_id="peer-A",
                amount=100,
            )
        )
        neg = AutonomousNegotiator(NegotiationConfig(min_trust_score=0.99))
        ctx = _make_ctx(store, reputation=_MockReputation({"peer-A": 0.1}))
        await neg.tick(ctx)
        assert store.get("t1").status == TaskStatus.FAILED
        assert "rejected" in store.get("t1").error

    async def test_skips_own_tasks(self):
        """Should skip tasks where requester == self (no self-negotiation)."""
        store = TaskStore()
        store.add(
            AgentTask(
                task_id="t1",
                description="my own task",
                requester_peer_id="QmLocal",
                amount=100,
            )
        )
        neg = AutonomousNegotiator()
        ctx = _make_ctx(store, peer_id="QmLocal")
        await neg.tick(ctx)
        assert store.get("t1").status == TaskStatus.PENDING  # unchanged
