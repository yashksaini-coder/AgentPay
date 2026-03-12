"""Tests for the agent discovery / capability registry."""

from __future__ import annotations

import time


from agentic_payments.discovery.models import AgentAdvertisement, AgentCapability
from agentic_payments.discovery.registry import CapabilityRegistry


# ── AgentCapability ─────────────────────────────────────────────

def test_capability_to_dict():
    cap = AgentCapability(service_type="llm-inference", price_per_call=1000, description="GPT-4")
    d = cap.to_dict()
    assert d["service_type"] == "llm-inference"
    assert d["price_per_call"] == 1000


def test_capability_from_dict():
    d = {"service_type": "image-gen", "price_per_call": 5000, "description": "DALL-E"}
    cap = AgentCapability.from_dict(d)
    assert cap.service_type == "image-gen"
    assert cap.price_per_call == 5000


# ── AgentAdvertisement ──────────────────────────────────────────

def test_advertisement_to_dict():
    ad = AgentAdvertisement(
        peer_id="QmPeer1",
        eth_address="0x1234567890abcdef1234567890abcdef12345678",
        capabilities=[AgentCapability("llm", 100)],
        addrs=["/ip4/127.0.0.1/tcp/9000"],
    )
    d = ad.to_dict()
    assert d["peer_id"] == "QmPeer1"
    assert len(d["capabilities"]) == 1


def test_advertisement_bazaar_format():
    ad = AgentAdvertisement(
        peer_id="QmPeer1",
        eth_address="0xabc",
        capabilities=[AgentCapability("llm", 100)],
    )
    bazaar = ad.to_bazaar_format()
    assert bazaar["provider"]["id"] == "QmPeer1"
    assert bazaar["resources"][0]["type"] == "llm"
    assert "payment-channel" in bazaar["resources"][0]["payment_types"]


def test_advertisement_from_dict():
    d = {
        "peer_id": "QmPeer2",
        "eth_address": "0xdef",
        "capabilities": [{"service_type": "data", "price_per_call": 50}],
        "addrs": ["/ip4/1.2.3.4/tcp/9000"],
    }
    ad = AgentAdvertisement.from_dict(d)
    assert ad.peer_id == "QmPeer2"
    assert len(ad.capabilities) == 1


# ── CapabilityRegistry ──────────────────────────────────────────

def test_registry_register_and_search():
    reg = CapabilityRegistry()
    ad = AgentAdvertisement(
        peer_id="QmA", eth_address="0xa",
        capabilities=[AgentCapability("llm", 100)],
    )
    reg.register(ad)
    results = reg.search()
    assert len(results) == 1
    assert results[0].peer_id == "QmA"


def test_registry_search_by_capability():
    reg = CapabilityRegistry()
    reg.register(AgentAdvertisement(
        peer_id="QmA", eth_address="0xa",
        capabilities=[AgentCapability("llm", 100)],
    ))
    reg.register(AgentAdvertisement(
        peer_id="QmB", eth_address="0xb",
        capabilities=[AgentCapability("image-gen", 500)],
    ))
    results = reg.search("llm")
    assert len(results) == 1
    assert results[0].peer_id == "QmA"


def test_registry_unregister():
    reg = CapabilityRegistry()
    reg.register(AgentAdvertisement(peer_id="QmA", eth_address="0xa"))
    reg.unregister("QmA")
    assert len(reg.search()) == 0


def test_registry_prune_stale():
    reg = CapabilityRegistry(stale_threshold=1)
    ad = AgentAdvertisement(peer_id="QmOld", eth_address="0x1")
    ad.last_seen = time.time() - 10
    reg._agents["QmOld"] = ad
    pruned = reg.prune_stale()
    assert pruned == 1
    assert len(reg.search()) == 0


def test_registry_bazaar_format():
    reg = CapabilityRegistry()
    reg.register(AgentAdvertisement(
        peer_id="QmA", eth_address="0xa",
        capabilities=[AgentCapability("llm", 100)],
    ))
    bazaar = reg.to_bazaar_format()
    assert len(bazaar) == 1
    assert bazaar[0]["provider"]["id"] == "QmA"
