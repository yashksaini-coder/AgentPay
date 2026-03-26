"""Tests for Strategy protocol and StrategyContext."""

from __future__ import annotations

from agentic_payments.agent.strategy import Strategy, StrategyContext
from agentic_payments.agent.task import TaskStore


class _NoopStrategy:
    """Minimal strategy for testing."""

    def __init__(self) -> None:
        self.tick_count = 0

    async def tick(self, ctx: StrategyContext) -> None:
        self.tick_count += 1


class TestStrategyProtocol:
    def test_noop_satisfies_protocol(self):
        """Any object with async tick(ctx) should satisfy Strategy."""
        assert isinstance(_NoopStrategy(), Strategy)

    def test_object_without_tick_does_not_satisfy(self):
        """Plain objects should not satisfy Strategy."""

        class NotAStrategy:
            pass

        assert not isinstance(NotAStrategy(), Strategy)


class TestStrategyContext:
    def test_construction(self):
        """StrategyContext should be constructable with required fields."""
        store = TaskStore()
        ctx = StrategyContext(
            peer_id="QmTest",
            eth_address="0xabc",
            channels=[],
            known_peers=["QmPeerA"],
            tasks=store,
            gateway=None,
            reputation_tracker=None,
            role=None,
        )
        assert ctx.peer_id == "QmTest"
        assert ctx.eth_address == "0xabc"
        assert ctx.tasks is store
        assert len(ctx.known_peers) == 1

    def test_frozen(self):
        """StrategyContext should be immutable (frozen dataclass)."""
        ctx = StrategyContext(
            peer_id="QmTest",
            eth_address="0xabc",
            channels=[],
            known_peers=[],
            tasks=TaskStore(),
            gateway=None,
            reputation_tracker=None,
            role=None,
        )
        try:
            ctx.peer_id = "changed"  # type: ignore[misc]
            assert False, "Should have raised"
        except AttributeError:
            pass

    async def test_multiple_strategies_run_in_sequence(self):
        """Multiple strategies should all get called with the same context."""
        s1 = _NoopStrategy()
        s2 = _NoopStrategy()
        ctx = StrategyContext(
            peer_id="QmTest",
            eth_address="0x0",
            channels=[],
            known_peers=[],
            tasks=TaskStore(),
            gateway=None,
            reputation_tracker=None,
            role=None,
        )
        for s in [s1, s2]:
            await s.tick(ctx)
        assert s1.tick_count == 1
        assert s2.tick_count == 1
