"""Tests for Executor protocol and implementations."""

from __future__ import annotations

from agentic_payments.agent.executor import CallbackExecutor, EchoExecutor, Executor
from agentic_payments.agent.task import AgentTask


class TestEchoExecutor:
    async def test_returns_description(self):
        """EchoExecutor should return 'echo: <description>'."""
        executor = EchoExecutor()
        task = AgentTask(task_id="t1", description="hello world")
        result = await executor.execute(task)
        assert result == "echo: hello world"

    async def test_satisfies_protocol(self):
        """EchoExecutor should satisfy the Executor protocol."""
        assert isinstance(EchoExecutor(), Executor)


class TestCallbackExecutor:
    async def test_wraps_async_callable(self):
        """CallbackExecutor should delegate to the provided async callable."""

        async def my_fn(task: AgentTask) -> str:
            return f"processed: {task.task_id}"

        executor = CallbackExecutor(my_fn)
        task = AgentTask(task_id="abc", description="test")
        result = await executor.execute(task)
        assert result == "processed: abc"

    async def test_propagates_errors(self):
        """CallbackExecutor should propagate exceptions from the callback."""

        async def failing_fn(task: AgentTask) -> str:
            raise RuntimeError("boom")

        executor = CallbackExecutor(failing_fn)
        task = AgentTask(task_id="t1", description="fail")
        try:
            await executor.execute(task)
            assert False, "Should have raised"
        except RuntimeError as exc:
            assert "boom" in str(exc)

    async def test_satisfies_protocol(self):
        """CallbackExecutor should satisfy the Executor protocol."""

        async def noop(task: AgentTask) -> str:
            return ""

        assert isinstance(CallbackExecutor(noop), Executor)
