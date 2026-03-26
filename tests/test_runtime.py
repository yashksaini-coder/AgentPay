"""Tests for AgentRuntime tick loop."""

from __future__ import annotations

import trio

from agentic_payments.agent.runtime import AgentRuntime
from agentic_payments.agent.strategy import StrategyContext
from agentic_payments.agent.task import AgentTask


class _CountingStrategy:
    def __init__(self) -> None:
        self.tick_count = 0

    async def tick(self, ctx: StrategyContext) -> None:
        self.tick_count += 1


class _FailingStrategy:
    async def tick(self, ctx: StrategyContext) -> None:
        raise RuntimeError("strategy boom")


class _MockNode:
    """Minimal mock that satisfies AgentRuntime._build_context."""

    def __init__(self) -> None:
        self.peer_id = _MockPeerID("QmTest")
        self.wallet = _MockWallet("0xabc")
        self.channel_manager = _MockChannelManager()
        self.discovery = _MockDiscovery()
        self.role_manager = _MockRoleManager()
        self.gateway = None
        self.reputation_tracker = None
        self.broadcaster = None

    async def pay(self, **kwargs):
        pass

    async def open_payment_channel(self, **kwargs):
        pass


class _MockPeerID:
    def __init__(self, val: str) -> None:
        self._val = val

    def to_base58(self) -> str:
        return self._val


class _MockWallet:
    def __init__(self, addr: str) -> None:
        self.address = addr


class _MockChannelManager:
    def list_channels(self):
        return []


class _MockDiscovery:
    def get_peers(self):
        return []


class _MockRoleManager:
    @property
    def role(self):
        return None


class TestAgentRuntime:
    async def test_starts_and_stops(self):
        """Runtime should start, run ticks, and stop cleanly."""
        node = _MockNode()
        strategy = _CountingStrategy()
        runtime = AgentRuntime(node=node, strategies=[strategy], tick_interval=0.05)

        async with trio.open_nursery() as nursery:
            await nursery.start(runtime.run)
            assert runtime.running is True
            await trio.sleep(0.15)
            runtime.stop()

        assert runtime.running is False
        assert strategy.tick_count >= 2

    async def test_tick_count_increments(self):
        """Tick count should increase each tick."""
        node = _MockNode()
        runtime = AgentRuntime(node=node, strategies=[], tick_interval=0.05)

        async with trio.open_nursery() as nursery:
            await nursery.start(runtime.run)
            await trio.sleep(0.15)
            assert runtime.tick_count >= 2
            runtime.stop()

    async def test_strategy_error_doesnt_crash(self):
        """Error in one strategy should not crash the loop or other strategies."""
        node = _MockNode()
        good = _CountingStrategy()
        bad = _FailingStrategy()
        runtime = AgentRuntime(
            node=node,
            strategies=[bad, good],
            tick_interval=0.05,
        )

        async with trio.open_nursery() as nursery:
            await nursery.start(runtime.run)
            await trio.sleep(0.15)
            runtime.stop()

        # Good strategy still ran despite bad one failing
        assert good.tick_count >= 2

    async def test_multiple_strategies_run(self):
        """All strategies should be called each tick."""
        node = _MockNode()
        s1 = _CountingStrategy()
        s2 = _CountingStrategy()
        runtime = AgentRuntime(node=node, strategies=[s1, s2], tick_interval=0.05)

        async with trio.open_nursery() as nursery:
            await nursery.start(runtime.run)
            await trio.sleep(0.15)
            runtime.stop()

        assert s1.tick_count >= 2
        assert s2.tick_count >= 2
        assert s1.tick_count == s2.tick_count

    async def test_status_dict(self):
        """status() should return correct runtime info."""
        node = _MockNode()
        s1 = _CountingStrategy()
        runtime = AgentRuntime(
            node=node,
            strategies=[s1],
            tick_interval=1.0,
        )
        status = runtime.status()
        assert status["running"] is False
        assert status["tick_count"] == 0
        assert "_CountingStrategy" in status["strategies"]

    async def test_task_store_accessible(self):
        """Strategies should be able to access task store via context."""
        node = _MockNode()
        accessed_store = []

        class _StoreReader:
            async def tick(self, ctx: StrategyContext) -> None:
                accessed_store.append(len(ctx.tasks))

        runtime = AgentRuntime(node=node, strategies=[_StoreReader()], tick_interval=0.05)
        runtime.task_store.add(AgentTask(task_id="t1", description="test"))

        async with trio.open_nursery() as nursery:
            await nursery.start(runtime.run)
            await trio.sleep(0.1)
            runtime.stop()

        # Strategy should have seen 1 task in the store
        assert any(count == 1 for count in accessed_store)
