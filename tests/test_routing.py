"""Tests for the multi-hop payment routing module."""

import hashlib
import os
import time

import pytest

from agentic_payments.routing.graph import NetworkGraph
from agentic_payments.routing.htlc import (
    HtlcError,
    HtlcManager,
    HtlcState,
    PendingHtlc,
    generate_preimage,
    verify_preimage,
)
from agentic_payments.routing.pathfinder import TIMEOUT_DELTA, find_route


# ── NetworkGraph ──────────────────────────────────────────────────


class TestNetworkGraph:
    def test_add_and_query_channel(self):
        g = NetworkGraph()
        g.add_channel("ch1", "A", "B", 1000)
        assert g.channel_count() == 1
        assert g.peer_count() == 2
        assert g.has_peer("A")
        assert g.has_peer("B")

    def test_bidirectional_neighbors(self):
        g = NetworkGraph()
        g.add_channel("ch1", "A", "B", 1000)
        neighbors_a = g.get_neighbors("A")
        neighbors_b = g.get_neighbors("B")
        assert len(neighbors_a) == 1
        assert neighbors_a[0][0] == "B"
        assert len(neighbors_b) == 1
        assert neighbors_b[0][0] == "A"

    def test_remove_channel(self):
        g = NetworkGraph()
        g.add_channel("ch1", "A", "B", 1000)
        g.remove_channel("ch1")
        assert g.channel_count() == 0
        assert g.get_neighbors("A") == []

    def test_remove_nonexistent_channel(self):
        g = NetworkGraph()
        g.remove_channel("nonexistent")  # Should not raise

    def test_multiple_channels_per_peer(self):
        g = NetworkGraph()
        g.add_channel("ch1", "A", "B", 1000)
        g.add_channel("ch2", "A", "C", 2000)
        g.add_channel("ch3", "B", "C", 500)
        neighbors = g.get_neighbors("A")
        assert len(neighbors) == 2
        peer_ids = {n[0] for n in neighbors}
        assert peer_ids == {"B", "C"}

    def test_to_dict(self):
        g = NetworkGraph()
        g.add_channel("ch1", "A", "B", 1000)
        d = g.to_dict()
        assert d["peer_count"] == 2
        assert d["channel_count"] == 1
        assert len(d["channels"]) == 1
        assert set(d["peers"]) == {"A", "B"}

    def test_prune_stale(self):
        g = NetworkGraph()
        g.add_channel("ch1", "A", "B", 1000)
        # Manually make it old
        g._edges["ch1"].last_seen = int(time.time()) - 7200
        removed = g.prune_stale()
        assert removed == 1
        assert g.channel_count() == 0

    def test_get_edge(self):
        g = NetworkGraph()
        g.add_channel("ch1", "A", "B", 1000)
        edge = g.get_edge("ch1")
        assert edge is not None
        assert edge.capacity == 1000
        assert g.get_edge("nonexistent") is None


# ── Pathfinder ────────────────────────────────────────────────────


class TestPathfinder:
    def _make_graph(self):
        """Create a test graph: A-B-C-D with varying capacities."""
        g = NetworkGraph()
        g.add_channel("ch_ab", "A", "B", 10000)
        g.add_channel("ch_bc", "B", "C", 5000)
        g.add_channel("ch_cd", "C", "D", 3000)
        return g

    def test_find_direct_route(self):
        g = NetworkGraph()
        g.add_channel("ch1", "A", "B", 1000)
        route = find_route(g, "A", "B", 500, int(time.time()) + 600)
        assert route is not None
        assert route.hop_count == 1
        assert route.hops[0].peer_id == "B"

    def test_find_multihop_route(self):
        g = self._make_graph()
        route = find_route(g, "A", "D", 1000, int(time.time()) + 600)
        assert route is not None
        assert route.hop_count == 3
        assert [h.peer_id for h in route.hops] == ["B", "C", "D"]

    def test_no_route_insufficient_capacity(self):
        g = self._make_graph()
        # ch_cd only has 3000 capacity
        route = find_route(g, "A", "D", 5000, int(time.time()) + 600)
        assert route is None

    def test_no_route_disconnected(self):
        g = NetworkGraph()
        g.add_channel("ch1", "A", "B", 1000)
        g.add_channel("ch2", "C", "D", 1000)
        route = find_route(g, "A", "D", 500, int(time.time()) + 600)
        assert route is None

    def test_same_source_and_dest(self):
        g = NetworkGraph()
        g.add_channel("ch1", "A", "B", 1000)
        route = find_route(g, "A", "A", 500, int(time.time()) + 600)
        assert route is None

    def test_timeout_decreases_per_hop(self):
        g = self._make_graph()
        base = int(time.time()) + 600
        route = find_route(g, "A", "D", 100, base)
        assert route is not None
        for i, hop in enumerate(route.hops):
            assert hop.timeout == base - (i * TIMEOUT_DELTA)

    def test_max_hops_limit(self):
        g = NetworkGraph()
        # Build a long chain: 0-1-2-3-4-5
        for i in range(5):
            g.add_channel(f"ch{i}", str(i), str(i + 1), 10000)
        # Should fail with max_hops=3 (need 5 hops)
        route = find_route(g, "0", "5", 100, int(time.time()) + 600, max_hops=3)
        assert route is None
        # Should succeed with max_hops=5
        route = find_route(g, "0", "5", 100, int(time.time()) + 600, max_hops=5)
        assert route is not None
        assert route.hop_count == 5

    def test_shortest_path_preferred(self):
        """When multiple paths exist, BFS finds the shortest."""
        g = NetworkGraph()
        # Direct path A->D
        g.add_channel("ch_ad", "A", "D", 10000)
        # Longer path A->B->C->D
        g.add_channel("ch_ab", "A", "B", 10000)
        g.add_channel("ch_bc", "B", "C", 10000)
        g.add_channel("ch_cd", "C", "D", 10000)
        route = find_route(g, "A", "D", 100, int(time.time()) + 600)
        assert route is not None
        assert route.hop_count == 1  # Direct path

    def test_route_to_dict(self):
        g = NetworkGraph()
        g.add_channel("ch1", "A", "B", 1000)
        route = find_route(g, "A", "B", 100, int(time.time()) + 600)
        d = route.to_dict()
        assert d["hop_count"] == 1
        assert len(d["hops"]) == 1
        assert d["total_amount"] == 100


# ── HTLC ──────────────────────────────────────────────────────────


class TestPreimage:
    def test_generate_and_verify(self):
        preimage, payment_hash = generate_preimage()
        assert len(preimage) == 32
        assert len(payment_hash) == 32
        assert verify_preimage(preimage, payment_hash)

    def test_wrong_preimage(self):
        _, payment_hash = generate_preimage()
        wrong = os.urandom(32)
        assert not verify_preimage(wrong, payment_hash)

    def test_hash_is_sha256(self):
        preimage, payment_hash = generate_preimage()
        assert hashlib.sha256(preimage).digest() == payment_hash


class TestHtlcManager:
    def _make_htlc(self, **kwargs):
        defaults = {
            "htlc_id": os.urandom(16),
            "channel_id": os.urandom(32),
            "payment_hash": os.urandom(32),
            "amount": 100000,
            "timeout": int(time.time()) + 600,
        }
        defaults.update(kwargs)
        return PendingHtlc(**defaults)

    def test_add_and_get(self):
        mgr = HtlcManager()
        htlc = self._make_htlc()
        mgr.add_htlc(htlc)
        assert mgr.get_htlc(htlc.htlc_id) is htlc

    def test_get_nonexistent(self):
        mgr = HtlcManager()
        with pytest.raises(KeyError):
            mgr.get_htlc(os.urandom(16))

    def test_fulfill(self):
        preimage, phash = generate_preimage()
        mgr = HtlcManager()
        htlc = self._make_htlc(payment_hash=phash)
        mgr.add_htlc(htlc)
        result = mgr.fulfill(htlc.htlc_id, preimage)
        assert result.state == HtlcState.FULFILLED

    def test_fulfill_wrong_preimage(self):
        _, phash = generate_preimage()
        mgr = HtlcManager()
        htlc = self._make_htlc(payment_hash=phash)
        mgr.add_htlc(htlc)
        with pytest.raises(HtlcError, match="Preimage does not match"):
            mgr.fulfill(htlc.htlc_id, os.urandom(32))

    def test_fulfill_already_fulfilled(self):
        preimage, phash = generate_preimage()
        mgr = HtlcManager()
        htlc = self._make_htlc(payment_hash=phash)
        mgr.add_htlc(htlc)
        mgr.fulfill(htlc.htlc_id, preimage)
        with pytest.raises(HtlcError, match="Cannot fulfill"):
            mgr.fulfill(htlc.htlc_id, preimage)

    def test_cancel(self):
        mgr = HtlcManager()
        htlc = self._make_htlc()
        mgr.add_htlc(htlc)
        result = mgr.cancel(htlc.htlc_id, "test reason")
        assert result.state == HtlcState.CANCELLED

    def test_cancel_already_cancelled(self):
        mgr = HtlcManager()
        htlc = self._make_htlc()
        mgr.add_htlc(htlc)
        mgr.cancel(htlc.htlc_id)
        with pytest.raises(HtlcError, match="Cannot cancel"):
            mgr.cancel(htlc.htlc_id)

    def test_get_by_payment_hash(self):
        mgr = HtlcManager()
        phash = os.urandom(32)
        h1 = self._make_htlc(payment_hash=phash)
        h2 = self._make_htlc(payment_hash=phash)
        h3 = self._make_htlc()  # Different hash
        mgr.add_htlc(h1)
        mgr.add_htlc(h2)
        mgr.add_htlc(h3)
        results = mgr.get_by_payment_hash(phash)
        assert len(results) == 2

    def test_pending_amount_for_channel(self):
        mgr = HtlcManager()
        cid = os.urandom(32)
        mgr.add_htlc(self._make_htlc(channel_id=cid, amount=100))
        mgr.add_htlc(self._make_htlc(channel_id=cid, amount=200))
        mgr.add_htlc(self._make_htlc(amount=300))  # Different channel
        assert mgr.pending_amount_for_channel(cid) == 300

    def test_expire_htlcs(self):
        mgr = HtlcManager()
        expired_htlc = self._make_htlc(timeout=int(time.time()) - 10)
        active_htlc = self._make_htlc(timeout=int(time.time()) + 600)
        mgr.add_htlc(expired_htlc)
        mgr.add_htlc(active_htlc)
        expired = mgr.expire_htlcs()
        assert len(expired) == 1
        assert expired[0].htlc_id == expired_htlc.htlc_id
        assert expired_htlc.state == HtlcState.EXPIRED
        assert active_htlc.state == HtlcState.PENDING

    def test_cleanup_settled(self):
        preimage, phash = generate_preimage()
        mgr = HtlcManager()
        h1 = self._make_htlc(payment_hash=phash)
        h2 = self._make_htlc()
        h3 = self._make_htlc()
        mgr.add_htlc(h1)
        mgr.add_htlc(h2)
        mgr.add_htlc(h3)
        mgr.fulfill(h1.htlc_id, preimage)
        mgr.cancel(h2.htlc_id)
        removed = mgr.cleanup_settled()
        assert removed == 2
        # h3 should still be there
        assert mgr.get_htlc(h3.htlc_id).state == HtlcState.PENDING

    def test_htlc_to_dict(self):
        htlc = self._make_htlc()
        d = htlc.to_dict()
        assert "htlc_id" in d
        assert "state" in d
        assert d["state"] == "PENDING"


# ── Channel HTLC locking ─────────────────────────────────────────


class TestChannelHtlcLocking:
    def _make_channel(self):
        from agentic_payments.payments.channel import PaymentChannel

        ch = PaymentChannel(
            channel_id=os.urandom(32),
            sender="0x" + "a" * 40,
            receiver="0x" + "b" * 40,
            total_deposit=10000,
        )
        ch.accept()
        ch.activate()
        return ch

    def test_lock_and_unlock(self):
        ch = self._make_channel()
        assert ch.available_balance == 10000
        ch.lock_htlc(3000)
        assert ch.available_balance == 7000
        assert ch.remaining_balance == 10000  # Still full (not paid yet)
        ch.unlock_htlc(3000)
        assert ch.available_balance == 10000

    def test_lock_exceeds_balance(self):
        from agentic_payments.payments.channel import ChannelError

        ch = self._make_channel()
        with pytest.raises(ChannelError, match="Insufficient balance"):
            ch.lock_htlc(20000)

    def test_lock_not_active(self):
        from agentic_payments.payments.channel import ChannelError, PaymentChannel

        ch = PaymentChannel(
            channel_id=os.urandom(32),
            sender="0x" + "a" * 40,
            receiver="0x" + "b" * 40,
            total_deposit=10000,
        )
        with pytest.raises(ChannelError, match="Cannot lock"):
            ch.lock_htlc(1000)


# ── Wire format for new message types ────────────────────────────


class TestNewMessageTypes:
    def test_htlc_propose_roundtrip(self):
        from agentic_payments.protocol.messages import (
            HtlcPropose,
            MessageType,
            from_wire,
            to_wire,
        )

        msg = HtlcPropose(
            channel_id=os.urandom(32),
            payment_hash=os.urandom(32),
            amount=50000,
            timeout=int(time.time()) + 600,
        )
        wire = to_wire(MessageType.HTLC_PROPOSE, msg)
        msg_type, parsed = from_wire(wire)
        assert msg_type == MessageType.HTLC_PROPOSE
        assert parsed.amount == 50000
        assert parsed.payment_hash == msg.payment_hash

    def test_htlc_fulfill_roundtrip(self):
        from agentic_payments.protocol.messages import (
            HtlcFulfill,
            MessageType,
            from_wire,
            to_wire,
        )

        msg = HtlcFulfill(
            channel_id=os.urandom(32),
            htlc_id=os.urandom(16),
            preimage=os.urandom(32),
        )
        wire = to_wire(MessageType.HTLC_FULFILL, msg)
        msg_type, parsed = from_wire(wire)
        assert msg_type == MessageType.HTLC_FULFILL
        assert parsed.preimage == msg.preimage

    def test_htlc_cancel_roundtrip(self):
        from agentic_payments.protocol.messages import (
            HtlcCancel,
            MessageType,
            from_wire,
            to_wire,
        )

        msg = HtlcCancel(
            channel_id=os.urandom(32),
            htlc_id=os.urandom(16),
            reason="timeout",
        )
        wire = to_wire(MessageType.HTLC_CANCEL, msg)
        msg_type, parsed = from_wire(wire)
        assert msg_type == MessageType.HTLC_CANCEL
        assert parsed.reason == "timeout"

    def test_channel_announce_roundtrip(self):
        from agentic_payments.protocol.messages import (
            ChannelAnnounce,
            MessageType,
            from_wire,
            to_wire,
        )

        msg = ChannelAnnounce(
            channel_id=os.urandom(32),
            peer_a="QmPeerA",
            peer_b="QmPeerB",
            capacity=100000,
        )
        wire = to_wire(MessageType.CHANNEL_ANNOUNCE, msg)
        msg_type, parsed = from_wire(wire)
        assert msg_type == MessageType.CHANNEL_ANNOUNCE
        assert parsed.peer_a == "QmPeerA"
        assert parsed.capacity == 100000
