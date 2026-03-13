"""Tests for the dynamic pricing engine."""

from __future__ import annotations

from agentic_payments.pricing.engine import PricingEngine, PricingPolicy
from agentic_payments.reputation.tracker import ReputationTracker


def _make_engine(policy: PricingPolicy | None = None) -> tuple[PricingEngine, ReputationTracker]:
    rep = ReputationTracker()
    engine = PricingEngine(reputation_tracker=rep, policy=policy)
    return engine, rep


def test_pricing_policy_serialization_roundtrip():
    policy = PricingPolicy(
        trust_discount_factor=0.2,
        congestion_premium_factor=0.4,
        min_price=100,
        max_price=5000,
        congestion_threshold=10,
    )
    d = policy.to_dict()
    restored = PricingPolicy.from_dict(d)
    assert restored.trust_discount_factor == 0.2
    assert restored.congestion_premium_factor == 0.4
    assert restored.min_price == 100
    assert restored.max_price == 5000
    assert restored.congestion_threshold == 10


def test_compute_price_neutral_trust_no_congestion():
    """Unknown peer (trust=0.5) with no congestion → base * (1 - 0.3*0.5) = base * 0.85."""
    engine, _rep = _make_engine()
    price = engine.compute_price(1000, "unknown-peer")
    # trust=0.5, discount=0.3*0.5=0.15, premium=0.0, multiplier=0.85
    assert price == 850


def test_compute_price_high_trust():
    """Peer with perfect trust → larger discount."""
    engine, rep = _make_engine()
    # Build up trust: many successful payments
    for _ in range(100):
        rep.record_payment_sent("trusted-peer", 100_000_000_000_000_000, response_time=0.5)
    trust = rep.get_trust_score("trusted-peer")
    assert trust > 0.8
    price = engine.compute_price(1000, "trusted-peer")
    # Higher trust → more discount → lower price
    assert price < 850  # less than neutral


def test_compute_price_low_trust():
    """Peer with low trust (0.0) → no discount."""
    engine, rep = _make_engine()
    # Create a peer with all failed payments
    for _ in range(50):
        rep.record_payment_failed("bad-peer")
    trust = rep.get_trust_score("bad-peer")
    assert trust < 0.5
    price = engine.compute_price(1000, "bad-peer")
    # Low trust → small discount → higher price than neutral
    assert price > 850 or price == 850  # at least neutral or higher


def test_get_quote_returns_breakdown():
    engine, _rep = _make_engine()
    quote = engine.get_quote(1000, "some-peer")
    assert "base_price" in quote
    assert "final_price" in quote
    assert "peer_id" in quote
    assert "trust_score" in quote
    assert "congestion_ratio" in quote
    assert "trust_discount_pct" in quote
    assert "congestion_premium_pct" in quote
    assert "policy" in quote
    assert quote["base_price"] == 1000
    assert quote["peer_id"] == "some-peer"


def test_update_policy_changes_behavior():
    engine, _rep = _make_engine()
    price_before = engine.compute_price(1000, "peer-X")

    # Double the discount factor
    new_policy = PricingPolicy(trust_discount_factor=0.6)
    engine.update_policy(new_policy)
    price_after = engine.compute_price(1000, "peer-X")
    # With neutral trust (0.5): before = 1 - 0.3*0.5 = 0.85, after = 1 - 0.6*0.5 = 0.70
    assert price_after < price_before


def test_pricing_policy_from_dict():
    d = {"trust_discount_factor": 0.15, "min_price": 50}
    policy = PricingPolicy.from_dict(d)
    assert policy.trust_discount_factor == 0.15
    assert policy.min_price == 50
    # Defaults for unspecified fields
    assert policy.congestion_premium_factor == 0.5
    assert policy.max_price == 0


def test_price_floor_enforcement():
    policy = PricingPolicy(min_price=500)
    engine, _rep = _make_engine(policy=policy)
    price = engine.compute_price(100, "peer-Y")
    # Base is 100, computed would be ~85, but floor is 500
    assert price >= 500


def test_price_ceiling_enforcement():
    policy = PricingPolicy(max_price=200)
    engine, _rep = _make_engine(policy=policy)
    price = engine.compute_price(1000, "peer-Z")
    # Base is 1000, computed would be ~850, but ceiling is 200
    assert price <= 200
