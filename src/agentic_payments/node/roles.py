"""Role-based agent coordination for multi-agent workflows.

Inspired by P2P-Federated-Learning's bootstrap/client/trainer pattern,
agents can advertise roles and coordinators can orchestrate work distribution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class AgentRole(StrEnum):
    """Predefined agent roles for coordination."""

    COORDINATOR = "coordinator"  # Orchestrates work rounds, assigns tasks
    WORKER = "worker"  # Executes compute tasks
    DATA_PROVIDER = "data_provider"  # Supplies data/context
    VALIDATOR = "validator"  # Verifies results
    GATEWAY = "gateway"  # Entry point / payment gateway


@dataclass
class RoleAssignment:
    """An agent's role assignment with optional metadata."""

    role: AgentRole
    capabilities: list[str] = field(default_factory=list)  # Specific sub-capabilities
    max_concurrent_tasks: int = 10
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "role": self.role.value,
            "capabilities": self.capabilities,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(d: dict) -> RoleAssignment:
        return RoleAssignment(
            role=AgentRole(d["role"]),
            capabilities=d.get("capabilities", []),
            max_concurrent_tasks=d.get("max_concurrent_tasks", 10),
            metadata=d.get("metadata", {}),
        )


@dataclass
class WorkRound:
    """A coordination round initiated by a coordinator."""

    round_id: str
    coordinator_peer_id: str
    task_type: str
    required_role: AgentRole = AgentRole.WORKER
    max_workers: int = 10
    reward_per_worker: int = 0  # Wei per completed task
    metadata: dict = field(default_factory=dict)
    assigned_workers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "round_id": self.round_id,
            "coordinator_peer_id": self.coordinator_peer_id,
            "task_type": self.task_type,
            "required_role": self.required_role.value,
            "max_workers": self.max_workers,
            "reward_per_worker": self.reward_per_worker,
            "metadata": self.metadata,
            "assigned_workers": self.assigned_workers,
        }

    @staticmethod
    def from_dict(d: dict) -> WorkRound:
        return WorkRound(
            round_id=d["round_id"],
            coordinator_peer_id=d["coordinator_peer_id"],
            task_type=d["task_type"],
            required_role=AgentRole(d.get("required_role", "worker")),
            max_workers=d.get("max_workers", 10),
            reward_per_worker=d.get("reward_per_worker", 0),
            metadata=d.get("metadata", {}),
            assigned_workers=d.get("assigned_workers", []),
        )


class RoleManager:
    """Manages agent role assignment and work round coordination."""

    def __init__(self) -> None:
        self._assignment: RoleAssignment | None = None
        self._work_rounds: dict[str, WorkRound] = {}  # round_id -> WorkRound

    @property
    def role(self) -> AgentRole | None:
        return self._assignment.role if self._assignment else None

    @property
    def assignment(self) -> RoleAssignment | None:
        return self._assignment

    def assign_role(self, assignment: RoleAssignment) -> None:
        """Set this agent's role."""
        self._assignment = assignment

    def clear_role(self) -> None:
        """Clear the agent's role assignment."""
        self._assignment = None

    def create_work_round(self, work_round: WorkRound) -> WorkRound:
        """Register a new work round (coordinator only)."""
        if self._assignment is None or self._assignment.role != AgentRole.COORDINATOR:
            raise ValueError("Only coordinators can create work rounds")
        self._work_rounds[work_round.round_id] = work_round
        return work_round

    def get_work_round(self, round_id: str) -> WorkRound | None:
        return self._work_rounds.get(round_id)

    def list_work_rounds(self) -> list[WorkRound]:
        return list(self._work_rounds.values())

    def assign_worker(self, round_id: str, worker_peer_id: str) -> bool:
        """Assign a worker to a work round. Returns True if successful."""
        if self.role != AgentRole.COORDINATOR:
            raise ValueError("Only coordinators can assign workers")
        wr = self._work_rounds.get(round_id)
        if wr is None:
            return False
        if len(wr.assigned_workers) >= wr.max_workers:
            return False
        if worker_peer_id in wr.assigned_workers:
            return False
        wr.assigned_workers.append(worker_peer_id)
        return True
