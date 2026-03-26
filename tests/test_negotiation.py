"""Tests for the negotiation protocol."""

from __future__ import annotations

import time

import pytest

from agentic_payments.negotiation.manager import NegotiationManager
from agentic_payments.negotiation.models import NegotiationState


def make_manager() -> NegotiationManager:
    return NegotiationManager()


def test_propose_creates_negotiation():
    mgr = make_manager()
    neg = mgr.propose("QmA", "QmB", "llm-inference", 1000, 50000)
    assert neg.state == NegotiationState.PROPOSED
    assert neg.proposed_price == 1000
    assert neg.current_price == 1000
    assert neg.initiator == "QmA"
    assert neg.responder == "QmB"


def test_counter_updates_price():
    mgr = make_manager()
    neg = mgr.propose("QmA", "QmB", "llm", 1000, 50000)
    neg2 = mgr.counter(neg.negotiation_id, "QmB", 800)
    assert neg2.state == NegotiationState.COUNTERED
    assert neg2.current_price == 800
    assert len(neg2.history) == 2


def test_accept_negotiation():
    mgr = make_manager()
    neg = mgr.propose("QmA", "QmB", "llm", 1000, 50000)
    mgr.counter(neg.negotiation_id, "QmB", 800)
    neg3 = mgr.accept(neg.negotiation_id, "QmA")
    assert neg3.state == NegotiationState.ACCEPTED
    assert neg3.current_price == 800


def test_reject_negotiation():
    mgr = make_manager()
    neg = mgr.propose("QmA", "QmB", "llm", 1000, 50000)
    neg2 = mgr.reject(neg.negotiation_id, "QmB")
    assert neg2.state == NegotiationState.REJECTED


def test_link_channel():
    mgr = make_manager()
    neg = mgr.propose("QmA", "QmB", "llm", 1000, 50000)
    mgr.accept(neg.negotiation_id, "QmB")
    neg3 = mgr.link_channel(neg.negotiation_id, "channel123")
    assert neg3.state == NegotiationState.CHANNEL_OPENED
    assert neg3.channel_id == "channel123"


def test_link_channel_requires_accepted():
    mgr = make_manager()
    neg = mgr.propose("QmA", "QmB", "llm", 1000, 50000)
    with pytest.raises(ValueError, match="Cannot link channel"):
        mgr.link_channel(neg.negotiation_id, "ch1")


def test_cannot_counter_after_accept():
    mgr = make_manager()
    neg = mgr.propose("QmA", "QmB", "llm", 1000, 50000)
    mgr.accept(neg.negotiation_id, "QmB")
    with pytest.raises(ValueError, match="not active"):
        mgr.counter(neg.negotiation_id, "QmA", 500)


def test_expiry():
    mgr = make_manager()
    neg = mgr.propose("QmA", "QmB", "llm", 1000, 50000)
    # Manually backdate timeout to simulate expiry
    neg.timeout = time.time() - 10
    retrieved = mgr.get(neg.negotiation_id)
    assert retrieved.state == NegotiationState.EXPIRED


def test_propose_rejects_past_timeout():
    mgr = make_manager()
    with pytest.raises(ValueError, match="future"):
        mgr.propose("QmA", "QmB", "llm", 1000, 50000, timeout=time.time() - 10)


def test_list_active():
    mgr = make_manager()
    neg1 = mgr.propose("QmA", "QmB", "llm", 1000, 50000)
    neg2 = mgr.propose("QmA", "QmC", "image", 2000, 60000)
    mgr.reject(neg2.negotiation_id, "QmC")
    active = mgr.list_active()
    assert len(active) == 1
    assert active[0].negotiation_id == neg1.negotiation_id


def test_list_all():
    mgr = make_manager()
    mgr.propose("QmA", "QmB", "llm", 1000, 50000)
    mgr.propose("QmA", "QmC", "image", 2000, 60000)
    assert len(mgr.list_all()) == 2


def test_only_participants_can_counter():
    mgr = make_manager()
    neg = mgr.propose("QmA", "QmB", "llm", 1000, 50000)
    with pytest.raises(ValueError, match="Only participants"):
        mgr.counter(neg.negotiation_id, "QmX", 500)


def test_to_dict():
    mgr = make_manager()
    neg = mgr.propose("QmA", "QmB", "llm", 1000, 50000)
    d = neg.to_dict()
    assert d["initiator"] == "QmA"
    assert d["state"] == "proposed"
    assert len(d["history"]) == 1
