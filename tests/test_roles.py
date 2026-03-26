"""Tests for role-based agent coordination."""

from __future__ import annotations

import pytest

from agentic_payments.node.roles import (
    AgentRole,
    RoleAssignment,
    RoleManager,
    WorkRound,
)


class TestAgentRole:
    def test_role_values(self):
        """All expected roles should exist."""
        assert AgentRole.COORDINATOR == "coordinator"
        assert AgentRole.WORKER == "worker"
        assert AgentRole.DATA_PROVIDER == "data_provider"
        assert AgentRole.VALIDATOR == "validator"
        assert AgentRole.GATEWAY == "gateway"

    def test_role_from_string(self):
        """Roles should be constructable from string values."""
        assert AgentRole("coordinator") == AgentRole.COORDINATOR
        assert AgentRole("worker") == AgentRole.WORKER


class TestRoleAssignment:
    def test_roundtrip(self):
        """RoleAssignment should survive dict serialization."""
        assignment = RoleAssignment(
            role=AgentRole.WORKER,
            capabilities=["llm-inference", "image-gen"],
            max_concurrent_tasks=5,
        )
        d = assignment.to_dict()
        restored = RoleAssignment.from_dict(d)
        assert restored.role == AgentRole.WORKER
        assert restored.capabilities == ["llm-inference", "image-gen"]
        assert restored.max_concurrent_tasks == 5


class TestRoleManager:
    def test_assign_and_get_role(self):
        """Should assign and retrieve a role."""
        rm = RoleManager()
        assert rm.role is None
        rm.assign_role(RoleAssignment(role=AgentRole.COORDINATOR))
        assert rm.role == AgentRole.COORDINATOR

    def test_clear_role(self):
        """Should clear the role assignment."""
        rm = RoleManager()
        rm.assign_role(RoleAssignment(role=AgentRole.WORKER))
        rm.clear_role()
        assert rm.role is None

    def test_create_work_round_as_coordinator(self):
        """Coordinators should be able to create work rounds."""
        rm = RoleManager()
        rm.assign_role(RoleAssignment(role=AgentRole.COORDINATOR))
        wr = rm.create_work_round(WorkRound(
            round_id="round-1",
            coordinator_peer_id="QmCoordinator",
            task_type="inference",
            reward_per_worker=1000,
        ))
        assert wr.round_id == "round-1"
        assert len(rm.list_work_rounds()) == 1

    def test_create_work_round_as_worker_fails(self):
        """Workers should not be able to create work rounds."""
        rm = RoleManager()
        rm.assign_role(RoleAssignment(role=AgentRole.WORKER))
        with pytest.raises(ValueError, match="coordinators"):
            rm.create_work_round(WorkRound(
                round_id="round-1",
                coordinator_peer_id="QmWorker",
                task_type="inference",
            ))

    def test_assign_worker_to_round(self):
        """Should assign workers to a work round up to max_workers."""
        rm = RoleManager()
        rm.assign_role(RoleAssignment(role=AgentRole.COORDINATOR))
        rm.create_work_round(WorkRound(
            round_id="round-1",
            coordinator_peer_id="QmCoordinator",
            task_type="inference",
            max_workers=2,
        ))
        assert rm.assign_worker("round-1", "QmWorker1") is True
        assert rm.assign_worker("round-1", "QmWorker2") is True
        # Max reached
        assert rm.assign_worker("round-1", "QmWorker3") is False
        # Duplicate
        assert rm.assign_worker("round-1", "QmWorker1") is False


class TestWorkRound:
    def test_roundtrip(self):
        """WorkRound should survive dict serialization."""
        wr = WorkRound(
            round_id="round-abc",
            coordinator_peer_id="QmCoord",
            task_type="training",
            required_role=AgentRole.WORKER,
            max_workers=5,
            reward_per_worker=2000,
            assigned_workers=["QmW1", "QmW2"],
        )
        d = wr.to_dict()
        restored = WorkRound.from_dict(d)
        assert restored.round_id == "round-abc"
        assert restored.required_role == AgentRole.WORKER
        assert restored.assigned_workers == ["QmW1", "QmW2"]
