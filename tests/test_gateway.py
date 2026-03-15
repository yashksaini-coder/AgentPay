"""Tests for the x402 resource gateway."""

from __future__ import annotations

from agentic_payments.gateway.x402 import (
    AccessDecision,
    GatedResource,
    PaymentProof,
    X402Gateway,
)


def test_register_resource():
    gw = X402Gateway(provider_id="QmA", wallet_address="0xabc")
    gw.register_resource(GatedResource(path="/api/infer", price=1000, description="LLM"))
    assert len(gw.list_resources()) == 1


def test_unregister_resource():
    gw = X402Gateway()
    gw.register_resource(GatedResource(path="/api/infer", price=1000))
    gw.unregister_resource("/api/infer")
    assert len(gw.list_resources()) == 0


def test_get_resource():
    gw = X402Gateway()
    gw.register_resource(GatedResource(path="/api/infer", price=1000))
    r = gw.get_resource("/api/infer")
    assert r is not None
    assert r.price == 1000
    assert gw.get_resource("/api/missing") is None


def test_bazaar_format():
    gw = X402Gateway(provider_id="QmA", wallet_address="0xabc")
    gw.register_resource(GatedResource(path="/api/infer", price=1000, description="LLM"))
    gw.register_resource(GatedResource(path="/api/image", price=5000, payment_type="x402"))
    bazaar = gw.to_bazaar_format()
    assert bazaar["provider"]["id"] == "QmA"
    assert bazaar["provider"]["protocol"] == "agentpay"
    assert len(bazaar["resources"]) == 2
    x402_resource = [r for r in bazaar["resources"] if r["path"] == "/api/image"][0]
    assert x402_resource["x402_compatible"] is True


def test_gated_resource_from_dict():
    d = {"path": "/api/test", "price": 500, "description": "Test", "payment_type": "htlc"}
    r = GatedResource.from_dict(d)
    assert r.path == "/api/test"
    assert r.payment_type == "htlc"


def test_is_gated():
    gw = X402Gateway()
    gw.register_resource(GatedResource(path="/api/infer", price=1000))
    assert gw.is_gated("/api/infer") is True
    assert gw.is_gated("/api/free") is False


def test_verify_access_ungated_path():
    """Non-gated paths should always be granted."""
    gw = X402Gateway()
    decision, meta = gw.verify_access("/api/free")
    assert decision == AccessDecision.GRANTED


def test_verify_access_no_proof_returns_402():
    """Gated path with no payment proof returns PAYMENT_REQUIRED."""
    gw = X402Gateway(provider_id="QmA", wallet_address="0xabc")
    gw.register_resource(GatedResource(path="/api/infer", price=1000))
    decision, meta = gw.verify_access("/api/infer")
    assert decision == AccessDecision.PAYMENT_REQUIRED
    assert meta["status"] == 402
    assert meta["x402"]["price"] == 1000
    assert meta["x402"]["wallet"] == "0xabc"


def test_verify_access_insufficient_amount():
    """Payment proof with insufficient amount is rejected."""
    gw = X402Gateway()
    gw.register_resource(GatedResource(path="/api/infer", price=1000))
    proof = PaymentProof(channel_id="abc", voucher_nonce=1, amount=500, sender="0x1")
    decision, meta = gw.verify_access("/api/infer", proof)
    assert decision == AccessDecision.INSUFFICIENT
    assert meta["error"] == "insufficient_payment"


def test_verify_access_sufficient_amount():
    """Payment proof with sufficient amount is granted (no channel manager)."""
    gw = X402Gateway()
    gw.register_resource(GatedResource(path="/api/infer", price=1000))
    proof = PaymentProof(channel_id="abc", voucher_nonce=1, amount=1000, sender="0x1")
    decision, meta = gw.verify_access("/api/infer", proof)
    assert decision == AccessDecision.GRANTED
    assert meta["price_charged"] == 1000


def test_access_log():
    """Access attempts are logged."""
    gw = X402Gateway()
    gw.register_resource(GatedResource(path="/api/infer", price=1000))
    gw.verify_access("/api/infer")  # 402
    proof = PaymentProof(channel_id="abc", voucher_nonce=1, amount=1000, sender="0x1")
    gw.verify_access("/api/infer", proof)  # granted
    log = gw.get_access_log()
    assert len(log) == 2
    assert log[0]["decision"] == "payment_required"
    assert log[1]["decision"] == "granted"


def test_payment_proof_from_dict():
    d = {"channel_id": "abc", "voucher_nonce": 5, "amount": 2000, "sender": "0x1"}
    proof = PaymentProof.from_dict(d)
    assert proof.channel_id == "abc"
    assert proof.voucher_nonce == 5
    assert proof.amount == 2000


def test_min_trust_score_gating():
    """Resource with min_trust_score should be included in dict."""
    r = GatedResource(path="/api/premium", price=5000, min_trust_score=0.7)
    d = r.to_dict()
    assert d["min_trust_score"] == 0.7
    r2 = GatedResource.from_dict(d)
    assert r2.min_trust_score == 0.7
