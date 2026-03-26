"""Task model and in-memory store for agent task lifecycle."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class TaskStatus(StrEnum):
    """Lifecycle states for an agent task."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    PAID = "paid"


# Valid transitions: current_status -> set of allowed next statuses
_VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.ASSIGNED, TaskStatus.FAILED},
    TaskStatus.ASSIGNED: {TaskStatus.EXECUTING, TaskStatus.FAILED},
    TaskStatus.EXECUTING: {TaskStatus.COMPLETED, TaskStatus.FAILED},
    TaskStatus.COMPLETED: {TaskStatus.PAID, TaskStatus.FAILED},
    TaskStatus.FAILED: set(),
    TaskStatus.PAID: set(),
}


@dataclass
class AgentTask:
    """A unit of work tracked by the agent runtime."""

    task_id: str
    description: str
    requester_peer_id: str = ""
    worker_peer_id: str = ""
    amount: int = 0
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "requester_peer_id": self.requester_peer_id,
            "worker_peer_id": self.worker_peer_id,
            "amount": self.amount,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class TaskStore:
    """In-memory task store with lifecycle management."""

    def __init__(self) -> None:
        self._tasks: dict[str, AgentTask] = {}

    def add(self, task: AgentTask) -> AgentTask:
        """Add a task to the store. Generates task_id if empty."""
        if not task.task_id:
            task.task_id = uuid.uuid4().hex[:12]
        if task.task_id in self._tasks:
            raise ValueError(f"Task {task.task_id} already exists")
        self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> AgentTask | None:
        return self._tasks.get(task_id)

    def update_status(self, task_id: str, new_status: TaskStatus) -> AgentTask:
        """Transition a task to a new status. Raises ValueError on invalid transition."""
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Task {task_id} not found")
        allowed = _VALID_TRANSITIONS.get(task.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition: {task.status} -> {new_status} "
                f"(allowed: {', '.join(sorted(allowed)) or 'none'})"
            )
        task.status = new_status
        task.updated_at = time.time()
        return task

    def by_status(self, status: TaskStatus) -> list[AgentTask]:
        """Return all tasks with the given status."""
        return [t for t in self._tasks.values() if t.status == status]

    def pending_tasks(self) -> list[AgentTask]:
        return self.by_status(TaskStatus.PENDING)

    def for_peer(self, peer_id: str) -> list[AgentTask]:
        """Return all tasks requested by or assigned to a peer."""
        return [
            t
            for t in self._tasks.values()
            if t.requester_peer_id == peer_id or t.worker_peer_id == peer_id
        ]

    def all_tasks(self) -> list[AgentTask]:
        return list(self._tasks.values())

    def __len__(self) -> int:
        return len(self._tasks)
