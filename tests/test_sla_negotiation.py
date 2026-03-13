"""Tests for SLA integration with the negotiation system."""

from __future__ import annotations

from agentic_payments.negotiation.manager import NegotiationManager
from agentic_payments.negotiation.models import SLATerms


def _make_sla(**kwargs) -> SLATerms:
    defaults = {
        "max_latency_ms": 150,
        "min_availability": 0.99,
        "max_error_rate": 0.02,
        "penalty_rate": 500,
    }
    defaults.update(kwargs)
    return SLATerms(**defaults)


def test_propose_with_sla_terms():
    mgr = NegotiationManager()
    sla = _make_sla()
    neg = mgr.propose("QmA", "QmB", "llm", 1000, 50000, sla_terms=sla)
    assert neg.sla_terms is not None
    assert neg.sla_terms.max_latency_ms == 150
    assert neg.sla_terms.max_error_rate == 0.02


def test_sla_terms_in_negotiation_to_dict():
    mgr = NegotiationManager()
    sla = _make_sla(max_latency_ms=200, penalty_rate=1000)
    neg = mgr.propose("QmA", "QmB", "llm", 1000, 50000, sla_terms=sla)
    d = neg.to_dict()
    assert "sla_terms" in d
    assert d["sla_terms"]["max_latency_ms"] == 200
    assert d["sla_terms"]["penalty_rate"] == 1000


def test_counter_with_sla_terms_update():
    mgr = NegotiationManager()
    sla_v1 = _make_sla(max_latency_ms=100)
    neg = mgr.propose("QmA", "QmB", "llm", 1000, 50000, sla_terms=sla_v1)

    sla_v2 = _make_sla(max_latency_ms=200)
    neg2 = mgr.counter(neg.negotiation_id, "QmB", 800, sla_terms=sla_v2)
    assert neg2.sla_terms is not None
    assert neg2.sla_terms.max_latency_ms == 200


def test_negotiation_event_includes_sla_terms():
    mgr = NegotiationManager()
    sla = _make_sla(penalty_rate=750)
    neg = mgr.propose("QmA", "QmB", "llm", 1000, 50000, sla_terms=sla)
    # The propose event should include sla_terms
    event_dict = neg.history[0].to_dict()
    assert "sla_terms" in event_dict
    assert event_dict["sla_terms"]["penalty_rate"] == 750
