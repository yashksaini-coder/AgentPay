"""Executor protocol and built-in implementations for task execution."""

from __future__ import annotations

from typing import Any, Callable, Coroutine, Protocol, runtime_checkable

from agentic_payments.agent.task import AgentTask


@runtime_checkable
class Executor(Protocol):
    """Protocol for task executors — any object with an async execute method."""

    async def execute(self, task: AgentTask) -> str:
        """Execute a task and return the result string. Raises on failure."""
        ...


class EchoExecutor:
    """Default no-op executor that returns the task description."""

    async def execute(self, task: AgentTask) -> str:
        return f"echo: {task.description}"


class CallbackExecutor:
    """Wraps a user-provided async callable as an Executor."""

    def __init__(self, callback: Callable[[AgentTask], Coroutine[Any, Any, str]]) -> None:
        self._callback = callback

    async def execute(self, task: AgentTask) -> str:
        return await self._callback(task)
