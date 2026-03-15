"""Tests for ERC-8004 agent identity module."""

from __future__ import annotations

from agentic_payments.identity.models import AgentIdentity, AgentRegistrationFile
from agentic_payments.identity.erc8004 import trust_score_to_erc8004, erc8004_to_trust_score
from agentic_payments.identity.bridge import IdentityBridge


def test_agent_identity_to_dict():
    identity = AgentIdentity(
        agent_id=42,
        eth_address="0xABC",
        peer_id="12D3KooW...",
        agent_uri="agentpay://12D3KooW",
        registered_on_chain=True,
        chain_id=31337,
        registration_tx="0xdeadbeef",
    )
    d = identity.to_dict()
    assert d["agent_id"] == 42
    assert d["registered_on_chain"] is True
    assert d["chain_id"] == 31337


def test_agent_identity_from_dict():
    d = {"agent_id": 7, "eth_address": "0x1", "peer_id": "QmA", "agent_uri": "uri"}
    identity = AgentIdentity.from_dict(d)
    assert identity.agent_id == 7
    assert identity.peer_id == "QmA"


def test_agent_identity_unregistered():
    identity = AgentIdentity(
        agent_id=None, eth_address="0x1", peer_id="QmA", agent_uri=""
    )
    assert identity.registered_on_chain is False
    assert identity.agent_id is None


def test_registration_file_to_dict():
    reg = AgentRegistrationFile(
        name="Test Agent",
        peer_id="12D3KooW...",
        eth_address="0xABC",
        capabilities=[{"service_type": "llm", "price_per_call": 1000}],
        endpoints=["/ip4/127.0.0.1/tcp/9000"],
    )
    d = reg.to_dict()
    assert d["name"] == "Test Agent"
    assert d["version"] == "1.0.0"
    assert len(d["capabilities"]) == 1
    assert "payment-channel" in d["payment_types"]


def test_registration_file_roundtrip():
    reg = AgentRegistrationFile(
        name="Agent X", peer_id="QmX", eth_address="0xX"
    )
    d = reg.to_dict()
    restored = AgentRegistrationFile.from_dict(d)
    assert restored.name == "Agent X"
    assert restored.peer_id == "QmX"


def test_trust_score_to_erc8004_normal():
    assert trust_score_to_erc8004(0.0) == 0
    assert trust_score_to_erc8004(0.5) == 50
    assert trust_score_to_erc8004(1.0) == 100
    assert trust_score_to_erc8004(0.73) == 73


def test_trust_score_to_erc8004_clamped():
    assert trust_score_to_erc8004(-0.5) == 0
    assert trust_score_to_erc8004(1.5) == 100


def test_erc8004_to_trust_score():
    assert erc8004_to_trust_score(0) == 0.0
    assert erc8004_to_trust_score(50) == 0.5
    assert erc8004_to_trust_score(100) == 1.0


def test_erc8004_to_trust_score_clamped():
    assert erc8004_to_trust_score(-10) == 0.0
    assert erc8004_to_trust_score(150) == 1.0


def test_score_roundtrip():
    """Converting back and forth should be approximately equal."""
    for score in [0.0, 0.1, 0.25, 0.5, 0.75, 0.99, 1.0]:
        erc = trust_score_to_erc8004(score)
        recovered = erc8004_to_trust_score(erc)
        assert abs(recovered - score) < 0.02


def test_identity_bridge_init():
    """IdentityBridge initializes without a client (mocked)."""

    class MockClient:
        pass

    bridge = IdentityBridge(
        client=MockClient(),  # type: ignore[arg-type]
        peer_id="12D3KooWTest",
        wallet_address="0xABC",
    )
    assert bridge.peer_id == "12D3KooWTest"
    assert bridge.wallet_address == "0xABC"
    assert bridge.identity is None
    assert bridge.agent_id is None


def test_identity_bridge_build_registration_file():
    class MockClient:
        pass

    bridge = IdentityBridge(
        client=MockClient(),  # type: ignore[arg-type]
        peer_id="QmPeer",
        wallet_address="0xWallet",
    )
    reg = bridge.build_registration_file(
        capabilities=[{"service_type": "compute", "price_per_call": 500}],
        addrs=["/ip4/0.0.0.0/tcp/9000"],
        name="My Agent",
    )
    assert reg["name"] == "My Agent"
    assert reg["peer_id"] == "QmPeer"
    assert reg["eth_address"] == "0xWallet"
    assert len(reg["capabilities"]) == 1
    assert len(reg["endpoints"]) == 1


def test_erc8004_config_defaults():
    from agentic_payments.config import ERC8004Config

    cfg = ERC8004Config()
    assert cfg.enabled is False
    assert cfg.identity_registry_address == ""
    assert cfg.reputation_registry_address == ""
    assert cfg.auto_register is False


def test_settings_includes_erc8004():
    from agentic_payments.config import Settings

    settings = Settings()
    assert hasattr(settings, "erc8004")
    assert settings.erc8004.enabled is False


def test_identity_abi_has_register():
    """Verify the ABI includes registerAgent function."""
    from agentic_payments.identity.erc8004 import ERC8004_IDENTITY_ABI

    func_names = [e["name"] for e in ERC8004_IDENTITY_ABI if e.get("type") == "function"]
    assert "registerAgent" in func_names
    assert "agentURI" in func_names
    assert "agentIdOf" in func_names
    assert "ownerOf" in func_names


def test_reputation_abi_has_feedback():
    """Verify the ABI includes submitFeedback function."""
    from agentic_payments.identity.erc8004 import ERC8004_REPUTATION_ABI

    func_names = [e["name"] for e in ERC8004_REPUTATION_ABI if e.get("type") == "function"]
    assert "submitFeedback" in func_names
    assert "getReputationSummary" in func_names
