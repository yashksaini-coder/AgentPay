"""Tests for the reputation tracker."""

from __future__ import annotations


from agentic_payments.reputation.tracker import PeerReputation, ReputationTracker


def test_empty_tracker_returns_neutral():
    tracker = ReputationTracker()
    assert tracker.get_trust_score("QmUnknown") == 0.5


def test_record_payment_sent():
    tracker = ReputationTracker()
    tracker.record_payment_sent("QmPeer1", 1000, response_time=0.5)
    rep = tracker.get_reputation("QmPeer1")
    assert rep is not None
    assert rep.payments_sent == 1
    assert rep.total_volume == 1000
    assert len(rep.response_times) == 1


def test_record_payment_received():
    tracker = ReputationTracker()
    tracker.record_payment_received("QmPeer1", 2000)
    rep = tracker.get_reputation("QmPeer1")
    assert rep.payments_received == 1
    assert rep.total_volume == 2000


def test_record_payment_failed():
    tracker = ReputationTracker()
    tracker.record_payment_failed("QmPeer1")
    rep = tracker.get_reputation("QmPeer1")
    assert rep.payments_failed == 1


def test_htlc_tracking():
    tracker = ReputationTracker()
    tracker.record_htlc_fulfilled("QmPeer1", response_time=0.3)
    tracker.record_htlc_cancelled("QmPeer1")
    rep = tracker.get_reputation("QmPeer1")
    assert rep.htlcs_fulfilled == 1
    assert rep.htlcs_cancelled == 1


def test_trust_score_improves_with_success():
    tracker = ReputationTracker()
    for _ in range(10):
        tracker.record_payment_sent("QmGood", 1_000_000_000_000_000_000, response_time=0.1)
    rep = tracker.get_reputation("QmGood")
    score = rep.trust_score
    assert score > 0.5  # should be better than neutral


def test_trust_score_drops_with_failures():
    tracker = ReputationTracker()
    for _ in range(10):
        tracker.record_payment_failed("QmBad")
    rep = tracker.get_reputation("QmBad")
    assert rep.success_rate == 0.0
    assert rep.trust_score < 0.5


def test_get_all():
    tracker = ReputationTracker()
    tracker.record_payment_sent("QmA", 100)
    tracker.record_payment_sent("QmB", 200)
    all_reps = tracker.get_all()
    assert len(all_reps) == 2


def test_peer_reputation_to_dict():
    rep = PeerReputation(peer_id="QmTest")
    rep.payments_sent = 5
    rep.total_volume = 10000
    d = rep.to_dict()
    assert d["peer_id"] == "QmTest"
    assert d["payments_sent"] == 5
    assert "trust_score" in d


def test_response_time_capped_at_100():
    tracker = ReputationTracker()
    for i in range(150):
        tracker.record_payment_sent("QmPeer", 100, response_time=float(i))
    rep = tracker.get_reputation("QmPeer")
    assert len(rep.response_times) == 100
