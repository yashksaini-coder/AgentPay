"""Tests for WorkerBehavior strategy."""

from __future__ import annotations

from agentic_payments.agent.executor import CallbackExecutor, EchoExecutor
from agentic_payments.agent.strategy import StrategyContext
from agentic_payments.agent.task import AgentTask, TaskStatus, TaskStore
from agentic_payments.agent.worker import WorkerBehavior


def _make_ctx(
    store: TaskStore,
    peer_id: str = "QmWorker",
    send_payment=None,
) -> StrategyContext:
    return StrategyContext(
        peer_id=peer_id,
        eth_address="0x0",
        channels=[],
        known_peers=[],
        tasks=store,
        gateway=None,
        reputation_tracker=None,
        role=None,
        send_payment=send_payment,
    )


class TestWorkerBehavior:
    async def test_executes_assigned_task(self):
        """Worker should execute assigned tasks and mark completed."""
        store = TaskStore()
        task = AgentTask(task_id="t1", description="hello", worker_peer_id="QmWorker")
        store.add(task)
        store.update_status("t1", TaskStatus.ASSIGNED)

        worker = WorkerBehavior(executor=EchoExecutor())
        ctx = _make_ctx(store)
        await worker.tick(ctx)

        assert store.get("t1").status == TaskStatus.COMPLETED
        assert store.get("t1").result == "echo: hello"

    async def test_uses_callback_executor(self):
        """Worker should use provided executor for execution."""
        store = TaskStore()
        task = AgentTask(task_id="t1", description="test", worker_peer_id="QmWorker")
        store.add(task)
        store.update_status("t1", TaskStatus.ASSIGNED)

        async def custom(t: AgentTask) -> str:
            return f"custom:{t.task_id}"

        worker = WorkerBehavior(executor=CallbackExecutor(custom))
        ctx = _make_ctx(store)
        await worker.tick(ctx)

        assert store.get("t1").result == "custom:t1"

    async def test_handles_executor_failure(self):
        """Worker should mark task FAILED on executor error."""
        store = TaskStore()
        task = AgentTask(task_id="t1", description="fail", worker_peer_id="QmWorker")
        store.add(task)
        store.update_status("t1", TaskStatus.ASSIGNED)

        async def boom(t: AgentTask) -> str:
            raise RuntimeError("executor error")

        worker = WorkerBehavior(executor=CallbackExecutor(boom))
        ctx = _make_ctx(store)
        await worker.tick(ctx)

        assert store.get("t1").status == TaskStatus.FAILED
        assert "executor error" in store.get("t1").error

    async def test_respects_capacity_limit(self):
        """Worker should not execute more tasks than max_concurrent."""
        store = TaskStore()
        for i in range(5):
            t = AgentTask(task_id=f"t{i}", description=f"task {i}", worker_peer_id="QmWorker")
            store.add(t)
            store.update_status(f"t{i}", TaskStatus.ASSIGNED)

        worker = WorkerBehavior(executor=EchoExecutor(), max_concurrent=2)
        ctx = _make_ctx(store)
        await worker.tick(ctx)

        completed = store.by_status(TaskStatus.COMPLETED)
        assigned = store.by_status(TaskStatus.ASSIGNED)
        # Only 2 should have been executed
        assert len(completed) == 2
        assert len(assigned) == 3

    async def test_skips_tasks_for_other_workers(self):
        """Worker should only execute tasks assigned to itself."""
        store = TaskStore()
        task = AgentTask(task_id="t1", description="other", worker_peer_id="QmOther")
        store.add(task)
        store.update_status("t1", TaskStatus.ASSIGNED)

        worker = WorkerBehavior(executor=EchoExecutor())
        ctx = _make_ctx(store, peer_id="QmWorker")
        await worker.tick(ctx)

        assert store.get("t1").status == TaskStatus.ASSIGNED  # unchanged

    async def test_no_payment_sent_by_worker(self):
        """Worker should NOT send payment — coordinator handles that."""
        store = TaskStore()
        task = AgentTask(
            task_id="t1",
            description="paid",
            worker_peer_id="QmWorker",
            requester_peer_id="QmRequester",
            amount=500,
        )
        store.add(task)
        store.update_status("t1", TaskStatus.ASSIGNED)

        payments = []

        async def mock_pay(**kwargs):
            payments.append(kwargs)

        worker = WorkerBehavior(executor=EchoExecutor())
        ctx = _make_ctx(store, send_payment=mock_pay)
        await worker.tick(ctx)

        assert len(payments) == 0  # Worker must not send payment
        assert store.get("t1").status == TaskStatus.COMPLETED
