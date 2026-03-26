"""Tests for AgentTask model and TaskStore."""

from __future__ import annotations

import pytest

from agentic_payments.agent.task import AgentTask, TaskStatus, TaskStore


class TestAgentTask:
    def test_default_status(self):
        """New tasks should start as PENDING."""
        task = AgentTask(task_id="t1", description="do something")
        assert task.status == TaskStatus.PENDING
        assert task.result == ""
        assert task.error == ""

    def test_to_dict_roundtrip(self):
        """Task dict should contain all fields."""
        task = AgentTask(task_id="t1", description="test", amount=100)
        d = task.to_dict()
        assert d["task_id"] == "t1"
        assert d["amount"] == 100
        assert d["status"] == "pending"


class TestTaskStore:
    def test_add_and_get(self):
        """Should store and retrieve a task by ID."""
        store = TaskStore()
        task = AgentTask(task_id="t1", description="work")
        store.add(task)
        assert store.get("t1") is task
        assert len(store) == 1

    def test_add_generates_id(self):
        """Should auto-generate ID if empty."""
        store = TaskStore()
        task = AgentTask(task_id="", description="auto-id")
        store.add(task)
        assert task.task_id != ""
        assert store.get(task.task_id) is task

    def test_add_duplicate_raises(self):
        """Should reject duplicate task IDs."""
        store = TaskStore()
        store.add(AgentTask(task_id="t1", description="first"))
        with pytest.raises(ValueError, match="already exists"):
            store.add(AgentTask(task_id="t1", description="second"))

    def test_lifecycle_pending_to_paid(self):
        """Full lifecycle: PENDING → ASSIGNED → EXECUTING → COMPLETED → PAID."""
        store = TaskStore()
        store.add(AgentTask(task_id="t1", description="full lifecycle"))
        store.update_status("t1", TaskStatus.ASSIGNED)
        store.update_status("t1", TaskStatus.EXECUTING)
        store.update_status("t1", TaskStatus.COMPLETED)
        store.update_status("t1", TaskStatus.PAID)
        assert store.get("t1").status == TaskStatus.PAID

    def test_invalid_transition_raises(self):
        """Should reject invalid status transitions."""
        store = TaskStore()
        store.add(AgentTask(task_id="t1", description="test"))
        with pytest.raises(ValueError, match="Invalid transition"):
            store.update_status("t1", TaskStatus.COMPLETED)

    def test_failed_is_terminal(self):
        """FAILED tasks cannot transition further."""
        store = TaskStore()
        store.add(AgentTask(task_id="t1", description="test"))
        store.update_status("t1", TaskStatus.FAILED)
        with pytest.raises(ValueError, match="Invalid transition"):
            store.update_status("t1", TaskStatus.PENDING)

    def test_by_status(self):
        """Should filter tasks by status."""
        store = TaskStore()
        store.add(AgentTask(task_id="t1", description="a"))
        store.add(AgentTask(task_id="t2", description="b"))
        store.update_status("t2", TaskStatus.ASSIGNED)
        assert len(store.by_status(TaskStatus.PENDING)) == 1
        assert len(store.by_status(TaskStatus.ASSIGNED)) == 1

    def test_for_peer(self):
        """Should find tasks by peer ID (requester or worker)."""
        store = TaskStore()
        store.add(AgentTask(task_id="t1", description="a", requester_peer_id="peer-A"))
        store.add(AgentTask(task_id="t2", description="b", worker_peer_id="peer-A"))
        store.add(AgentTask(task_id="t3", description="c", requester_peer_id="peer-B"))
        assert len(store.for_peer("peer-A")) == 2
        assert len(store.for_peer("peer-B")) == 1
        assert len(store.for_peer("peer-X")) == 0

    def test_get_missing_returns_none(self):
        """get() should return None for missing task IDs."""
        store = TaskStore()
        assert store.get("nonexistent") is None

    def test_update_missing_raises(self):
        """update_status() should raise KeyError for missing tasks."""
        store = TaskStore()
        with pytest.raises(KeyError, match="not found"):
            store.update_status("nonexistent", TaskStatus.ASSIGNED)
