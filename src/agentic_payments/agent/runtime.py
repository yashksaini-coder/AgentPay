"""Agent runtime — tick-based loop that drives autonomous agent behavior."""

from __future__ import annotations

from typing import Any

import structlog
import trio

from agentic_payments.agent.executor import EchoExecutor, Executor
from agentic_payments.agent.strategy import StrategyContext
from agentic_payments.agent.task import TaskStore

logger = structlog.get_logger(__name__)


class AgentRuntime:
    """Tick-based runtime that drives strategies for autonomous agent behavior.

    Spawned in the AgentNode's trio nursery. Each tick:
    1. Builds a StrategyContext snapshot from the node
    2. Calls each strategy's tick(ctx) in sequence
    3. Logs metrics

    Errors in individual strategies are logged but don't crash the loop.
    """

    def __init__(
        self,
        node: Any,
        strategies: list[Any] | None = None,
        executor: Executor | None = None,
        tick_interval: float = 5.0,
    ) -> None:
        self.node = node
        self.strategies: list[Any] = strategies or []
        self.executor: Executor = executor or EchoExecutor()
        self.tick_interval = tick_interval
        self.task_store = TaskStore()
        self.tick_count = 0
        self._running = False
        self._cancel_scope: trio.CancelScope | None = None

    @property
    def running(self) -> bool:
        return self._running

    def _build_context(self) -> StrategyContext:
        """Build a StrategyContext snapshot from the current node state."""
        node = self.node

        peer_id = ""
        if node.peer_id is not None:
            peer_id = node.peer_id.to_base58()

        eth_address = ""
        if node.wallet is not None:
            eth_address = node.wallet.address

        channels: list[Any] = []
        if node.channel_manager is not None:
            channels = node.channel_manager.list_channels()

        known_peers: list[str] = []
        if node.discovery is not None:
            try:
                known_peers = [
                    p.get("peer_id", "") for p in node.discovery.get_peers() if p.get("peer_id")
                ]
            except Exception:
                pass

        role = None
        if hasattr(node, "role_manager") and node.role_manager is not None:
            role = node.role_manager.role

        gateway = getattr(node, "gateway", None)
        reputation = getattr(node, "reputation_tracker", None)

        # Build callbacks
        send_payment = None
        if hasattr(node, "pay") and callable(node.pay):
            send_payment = node.pay

        open_channel = None
        if hasattr(node, "open_payment_channel") and callable(node.open_payment_channel):
            open_channel = node.open_payment_channel

        broadcast = None
        if node.broadcaster is not None:
            async def _broadcast(data: dict) -> None:
                from agentic_payments.pubsub.topics import TOPIC_AGENT_CAPABILITIES

                await node.broadcaster.publish(TOPIC_AGENT_CAPABILITIES, data)

            broadcast = _broadcast

        return StrategyContext(
            peer_id=peer_id,
            eth_address=eth_address,
            channels=channels,
            known_peers=known_peers,
            tasks=self.task_store,
            gateway=gateway,
            reputation_tracker=reputation,
            role=role,
            send_payment=send_payment,
            open_channel=open_channel,
            broadcast=broadcast,
        )

    async def run(self, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED) -> None:
        """Run the tick loop. Call via nursery.start(runtime.run) for coordination."""
        self._running = True
        self._cancel_scope = trio.CancelScope()
        task_status.started()

        logger.info(
            "agent_runtime_started",
            strategies=len(self.strategies),
            tick_interval=self.tick_interval,
        )

        try:
            with self._cancel_scope:
                while True:
                    await self._tick()
                    await trio.sleep(self.tick_interval)
        finally:
            self._running = False
            logger.info("agent_runtime_stopped", ticks=self.tick_count)

    async def _tick(self) -> None:
        """Execute one tick: build context, run all strategies."""
        self.tick_count += 1
        ctx = self._build_context()

        for strategy in self.strategies:
            try:
                await strategy.tick(ctx)
            except Exception:
                logger.exception(
                    "strategy_error",
                    strategy=type(strategy).__name__,
                    tick=self.tick_count,
                )

    def stop(self) -> None:
        """Stop the runtime loop."""
        if self._cancel_scope is not None:
            self._cancel_scope.cancel()

    def status(self) -> dict:
        """Return runtime status for the API."""
        return {
            "running": self._running,
            "tick_count": self.tick_count,
            "tick_interval": self.tick_interval,
            "strategies": [type(s).__name__ for s in self.strategies],
            "task_count": len(self.task_store),
            "pending_tasks": len(self.task_store.pending_tasks()),
        }
