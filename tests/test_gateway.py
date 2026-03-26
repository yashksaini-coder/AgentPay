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
    gw = X402Gateway(provider_id="QmA", wallet_address="0xabc", network="ethereum-sepolia")
    gw.register_resource(GatedResource(path="/api/infer", price=1000, description="LLM"))
    gw.register_resource(GatedResource(path="/api/image", price=5000, payment_type="x402"))
    bazaar = gw.to_bazaar_format()
    assert bazaar["provider"]["id"] == "QmA"
    assert bazaar["provider"]["network"] == "ethereum-sepolia"
    assert len(bazaar["resources"]) == 2
    res = bazaar["resources"][0]
    assert "scheme" in res
    assert res["scheme"] == "exact"
    assert "maxAmountRequired" in res
    assert "payTo" in res


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
    """Gated path with no payment proof returns x402 V1 spec-compliant 402."""
    gw = X402Gateway(provider_id="QmA", wallet_address="0xabc", network="ethereum-sepolia")
    gw.register_resource(GatedResource(path="/api/infer", price=1000))
    decision, meta = gw.verify_access("/api/infer")
    assert decision == AccessDecision.PAYMENT_REQUIRED
    # x402 V1 spec compliance
    assert meta["x402Version"] == 1
    assert len(meta["accepts"]) == 1
    req = meta["accepts"][0]
    assert req["scheme"] == "exact"
    assert req["network"] == "ethereum-sepolia"
    assert req["maxAmountRequired"] == "1000"
    assert req["payTo"] == "0xabc"
    assert req["resource"] == "/api/infer"


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


# ── One-Shot x402 Payment Tests ───────────────────────────────


def test_oneshot_sufficient_payment():
    """One-shot payment with sufficient amount should be granted."""
    gw = X402Gateway()
    gw.register_resource(GatedResource(path="/api/infer", price=1000))
    decision, meta = gw.settle_oneshot(
        path="/api/infer", sender="0x1", amount=1000
    )
    assert decision == AccessDecision.GRANTED
    assert meta["payment_mode"] == "oneshot"
    assert meta["price_charged"] == 1000


def test_oneshot_insufficient_payment():
    """One-shot payment with insufficient amount should be rejected."""
    gw = X402Gateway()
    gw.register_resource(GatedResource(path="/api/infer", price=1000))
    decision, meta = gw.settle_oneshot(
        path="/api/infer", sender="0x1", amount=500
    )
    assert decision == AccessDecision.INSUFFICIENT
    assert meta["error"] == "insufficient_payment"


def test_oneshot_ungated_resource():
    """One-shot on a non-gated path should pass through."""
    gw = X402Gateway()
    decision, meta = gw.settle_oneshot(
        path="/api/free", sender="0x1", amount=0
    )
    assert decision == AccessDecision.GRANTED


def test_oneshot_with_task_id():
    """One-shot payment should carry task_id for correlation."""
    gw = X402Gateway()
    gw.register_resource(GatedResource(path="/api/infer", price=1000))
    decision, meta = gw.settle_oneshot(
        path="/api/infer", sender="0x1", amount=1000, task_id="task-xyz"
    )
    assert decision == AccessDecision.GRANTED
    assert meta["task_id"] == "task-xyz"


def test_oneshot_logged():
    """One-shot access attempts should appear in the access log."""
    gw = X402Gateway()
    gw.register_resource(GatedResource(path="/api/infer", price=1000))
    gw.settle_oneshot(path="/api/infer", sender="0x1", amount=1000)
    gw.settle_oneshot(path="/api/infer", sender="0x2", amount=100)
    log = gw.get_access_log()
    assert len(log) == 2
    assert log[0]["decision"] == "granted"
    assert log[1]["decision"] == "insufficient"


def test_oneshot_error_codes():
    """One-shot rejections should include standardized error codes."""
    gw = X402Gateway()
    gw.register_resource(GatedResource(path="/api/infer", price=1000))
    _, meta = gw.settle_oneshot(path="/api/infer", sender="0x1", amount=100)
    assert "error_code" in meta
    assert meta["error_code"] == "INSUFFICIENT_PAYMENT"
