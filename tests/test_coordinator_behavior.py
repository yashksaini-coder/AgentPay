"""Tests for CoordinatorBehavior strategy."""

from __future__ import annotations

from agentic_payments.agent.coordinator import CoordinatorBehavior
from agentic_payments.agent.strategy import StrategyContext
from agentic_payments.agent.task import AgentTask, TaskStatus, TaskStore
from agentic_payments.node.roles import AgentRole


class _MockReputation:
    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self._scores = scores or {}

    def get_trust_score(self, peer_id: str) -> float:
        return self._scores.get(peer_id, 0.5)


def _make_ctx(
    store: TaskStore,
    peer_id: str = "QmCoordinator",
    peers: list[str] | None = None,
    reputation: _MockReputation | None = None,
    send_payment=None,
    broadcast=None,
) -> StrategyContext:
    return StrategyContext(
        peer_id=peer_id,
        eth_address="0x0",
        channels=[],
        known_peers=peers or [],
        tasks=store,
        gateway=None,
        reputation_tracker=reputation,
        role=AgentRole.COORDINATOR,
        send_payment=send_payment,
        broadcast=broadcast,
    )


class TestCoordinatorBehavior:
    async def test_assigns_pending_to_worker(self):
        """Coordinator should assign pending tasks to available workers."""
        store = TaskStore()
        store.add(AgentTask(task_id="t1", description="work"))

        coord = CoordinatorBehavior()
        ctx = _make_ctx(store, peers=["QmCoordinator", "QmWorkerA"])
        await coord.tick(ctx)

        assert store.get("t1").status == TaskStatus.ASSIGNED
        assert store.get("t1").worker_peer_id == "QmWorkerA"

    async def test_selects_by_reputation(self):
        """Coordinator should prefer higher-reputation workers."""
        store = TaskStore()
        store.add(AgentTask(task_id="t1", description="work"))

        rep = _MockReputation({"QmLow": 0.2, "QmHigh": 0.9})
        coord = CoordinatorBehavior()
        ctx = _make_ctx(
            store,
            peers=["QmCoordinator", "QmLow", "QmHigh"],
            reputation=rep,
        )
        await coord.tick(ctx)

        assert store.get("t1").worker_peer_id == "QmHigh"

    async def test_no_workers_available(self):
        """Tasks should stay PENDING if no workers available."""
        store = TaskStore()
        store.add(AgentTask(task_id="t1", description="work"))

        coord = CoordinatorBehavior()
        ctx = _make_ctx(store, peers=["QmCoordinator"])  # Only self
        await coord.tick(ctx)

        assert store.get("t1").status == TaskStatus.PENDING

    async def test_settles_payment_on_completion(self):
        """Coordinator should pay workers for completed tasks."""
        store = TaskStore()
        task = AgentTask(task_id="t1", description="done", worker_peer_id="QmWorkerA", amount=300)
        store.add(task)
        store.update_status("t1", TaskStatus.ASSIGNED)
        store.update_status("t1", TaskStatus.EXECUTING)
        store.update_status("t1", TaskStatus.COMPLETED)

        payments = []

        async def mock_pay(**kwargs):
            payments.append(kwargs)

        coord = CoordinatorBehavior()
        ctx = _make_ctx(store, send_payment=mock_pay)
        await coord.tick(ctx)

        assert store.get("t1").status == TaskStatus.PAID
        assert len(payments) == 1
        assert payments[0]["amount"] == 300

    async def test_settles_free_task(self):
        """Tasks with amount=0 should be marked PAID without payment call."""
        store = TaskStore()
        task = AgentTask(task_id="t1", description="free", worker_peer_id="QmW", amount=0)
        store.add(task)
        store.update_status("t1", TaskStatus.ASSIGNED)
        store.update_status("t1", TaskStatus.EXECUTING)
        store.update_status("t1", TaskStatus.COMPLETED)

        coord = CoordinatorBehavior()
        ctx = _make_ctx(store)
        await coord.tick(ctx)

        assert store.get("t1").status == TaskStatus.PAID

    async def test_broadcasts_assignment(self):
        """Coordinator should broadcast task assignments."""
        store = TaskStore()
        store.add(AgentTask(task_id="t1", description="work"))

        broadcasts = []

        async def mock_broadcast(data: dict) -> None:
            broadcasts.append(data)

        coord = CoordinatorBehavior()
        ctx = _make_ctx(
            store,
            peers=["QmCoordinator", "QmWorkerA"],
            broadcast=mock_broadcast,
        )
        await coord.tick(ctx)

        assert len(broadcasts) == 1
        assert broadcasts[0]["type"] == "task_assignment"
        assert broadcasts[0]["task_id"] == "t1"
