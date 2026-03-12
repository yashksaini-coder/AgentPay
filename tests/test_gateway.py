"""Tests for the x402 resource gateway."""

from __future__ import annotations

from agentic_payments.gateway.x402 import GatedResource, X402Gateway


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
