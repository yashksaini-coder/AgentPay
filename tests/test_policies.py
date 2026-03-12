"""Tests for the wallet policy engine."""

from __future__ import annotations


import pytest

from agentic_payments.policies.engine import PolicyEngine, PolicyViolation, WalletPolicy


def test_default_policy_allows_all():
    engine = PolicyEngine()
    engine.check_payment(1_000_000, "QmPeer1")  # should not raise


def test_max_spend_per_tx():
    engine = PolicyEngine(WalletPolicy(max_spend_per_tx=1000))
    engine.check_payment(1000, "QmPeer1")  # ok
    with pytest.raises(PolicyViolation, match="per-transaction limit"):
        engine.check_payment(1001, "QmPeer1")


def test_max_total_spend():
    engine = PolicyEngine(WalletPolicy(max_total_spend=5000))
    engine.check_payment(3000, "QmPeer1")
    engine.record_payment(3000)
    with pytest.raises(PolicyViolation, match="(?i)total spend"):
        engine.check_payment(3000, "QmPeer1")


def test_rate_limit():
    engine = PolicyEngine(WalletPolicy(rate_limit_per_min=2))
    engine.check_payment(100, "QmPeer1")
    engine.record_payment(100)
    engine.check_payment(100, "QmPeer1")
    engine.record_payment(100)
    with pytest.raises(PolicyViolation, match="Rate limit"):
        engine.check_payment(100, "QmPeer1")


def test_peer_whitelist():
    engine = PolicyEngine(WalletPolicy(peer_whitelist=["QmAllowed"]))
    engine.check_payment(100, "QmAllowed")  # ok
    with pytest.raises(PolicyViolation, match="not in whitelist"):
        engine.check_payment(100, "QmBlocked")


def test_peer_blacklist():
    engine = PolicyEngine(WalletPolicy(peer_blacklist=["QmBad"]))
    engine.check_payment(100, "QmGood")  # ok
    with pytest.raises(PolicyViolation, match="blacklisted"):
        engine.check_payment(100, "QmBad")


def test_check_channel_open_blacklist():
    engine = PolicyEngine(WalletPolicy(peer_blacklist=["QmBad"]))
    with pytest.raises(PolicyViolation, match="blacklisted"):
        engine.check_channel_open(10000, "QmBad")


def test_check_channel_open_total_spend():
    engine = PolicyEngine(WalletPolicy(max_total_spend=5000))
    engine.record_payment(4000)
    with pytest.raises(PolicyViolation, match="total spend limit"):
        engine.check_channel_open(2000, "QmPeer1")


def test_get_stats():
    engine = PolicyEngine(WalletPolicy(max_spend_per_tx=1000))
    engine.record_payment(500)
    stats = engine.get_stats()
    assert stats["total_spent"] == 500
    assert stats["payments_last_minute"] == 1
    assert stats["policy"]["max_spend_per_tx"] == 1000


def test_update_policy():
    engine = PolicyEngine()
    new_policy = WalletPolicy(max_spend_per_tx=2000, peer_blacklist=["QmBad"])
    engine.update_policy(new_policy)
    assert engine.policy.max_spend_per_tx == 2000
    with pytest.raises(PolicyViolation, match="blacklisted"):
        engine.check_payment(100, "QmBad")


def test_policy_from_dict():
    d = {"max_spend_per_tx": 5000, "peer_whitelist": ["QmA", "QmB"]}
    p = WalletPolicy.from_dict(d)
    assert p.max_spend_per_tx == 5000
    assert p.peer_whitelist == ["QmA", "QmB"]
