"""Data models for ERC-8004 agent identity."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class AgentIdentity:
    """On-chain agent identity from the ERC-8004 Identity Registry."""

    agent_id: int | None  # ERC-721 token ID, None if not registered
    eth_address: str
    peer_id: str
    agent_uri: str  # Off-chain registration file URL/CID
    registered_on_chain: bool = False
    chain_id: int = 1
    registration_tx: str | None = None

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "eth_address": self.eth_address,
            "peer_id": self.peer_id,
            "agent_uri": self.agent_uri,
            "registered_on_chain": self.registered_on_chain,
            "chain_id": self.chain_id,
            "registration_tx": self.registration_tx,
        }

    @staticmethod
    def from_dict(d: dict) -> AgentIdentity:
        return AgentIdentity(
            agent_id=d.get("agent_id"),
            eth_address=d.get("eth_address", ""),
            peer_id=d.get("peer_id", ""),
            agent_uri=d.get("agent_uri", ""),
            registered_on_chain=d.get("registered_on_chain", False),
            chain_id=d.get("chain_id", 1),
            registration_tx=d.get("registration_tx"),
        )


@dataclass
class AgentRegistrationFile:
    """Off-chain JSON file pointed to by ERC-8004 agentURI.

    Contains the agent's capabilities, endpoints, and identity keys
    for discovery and verification by other agents.
    """

    name: str
    version: str = "1.0.0"
    peer_id: str = ""
    eth_address: str = ""
    capabilities: list[dict] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    public_key_ed25519: str = ""  # hex-encoded
    chain_type: str = "ethereum"
    payment_types: list[str] = field(default_factory=lambda: ["payment-channel", "htlc"])
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "peer_id": self.peer_id,
            "eth_address": self.eth_address,
            "capabilities": self.capabilities,
            "endpoints": self.endpoints,
            "public_key_ed25519": self.public_key_ed25519,
            "chain_type": self.chain_type,
            "payment_types": self.payment_types,
            "timestamp": self.timestamp,
        }

    @staticmethod
    def from_dict(d: dict) -> AgentRegistrationFile:
        return AgentRegistrationFile(
            name=d.get("name", ""),
            version=d.get("version", "1.0.0"),
            peer_id=d.get("peer_id", ""),
            eth_address=d.get("eth_address", ""),
            capabilities=d.get("capabilities", []),
            endpoints=d.get("endpoints", []),
            public_key_ed25519=d.get("public_key_ed25519", ""),
            chain_type=d.get("chain_type", "ethereum"),
            payment_types=d.get("payment_types", ["payment-channel", "htlc"]),
            timestamp=d.get("timestamp", time.time()),
        )
