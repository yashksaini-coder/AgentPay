"""Strategy protocol and context for the agent tick loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentic_payments.agent.task import TaskStore
    from agentic_payments.gateway.x402 import X402Gateway
    from agentic_payments.node.roles import AgentRole
    from agentic_payments.reputation.tracker import ReputationTracker


@dataclass(frozen=True)
class StrategyContext:
    """Read-only snapshot of node state passed to strategies each tick."""

    peer_id: str
    eth_address: str
    channels: list[Any]
    known_peers: list[str]
    tasks: TaskStore
    gateway: X402Gateway | None
    reputation_tracker: ReputationTracker | None
    role: AgentRole | None

    # Callbacks for strategies to trigger actions
    send_payment: Callable[..., Coroutine[Any, Any, Any]] | None = None
    open_channel: Callable[..., Coroutine[Any, Any, Any]] | None = None
    broadcast: Callable[..., Coroutine[Any, Any, None]] | None = None


@runtime_checkable
class Strategy(Protocol):
    """Protocol for pluggable agent strategies — any object with async tick(ctx)."""

    async def tick(self, ctx: StrategyContext) -> None:
        """Run one tick of strategy logic."""
        ...
