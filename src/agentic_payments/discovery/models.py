"""Discovery data models for agent capability advertisements."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class AgentCapability:
    """A single capability (service) offered by an agent."""

    service_type: str  # e.g. "llm-inference", "image-gen", "data-retrieval"
    price_per_call: int  # Wei per invocation
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "service_type": self.service_type,
            "price_per_call": self.price_per_call,
            "description": self.description,
        }

    @staticmethod
    def from_dict(d: dict) -> AgentCapability:
        return AgentCapability(
            service_type=d["service_type"],
            price_per_call=d["price_per_call"],
            description=d.get("description", ""),
        )


@dataclass
class AgentAdvertisement:
    """Advertisement broadcast by an agent on the capability topic."""

    peer_id: str
    eth_address: str
    capabilities: list[AgentCapability] = field(default_factory=list)
    addrs: list[str] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "peer_id": self.peer_id,
            "eth_address": self.eth_address,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "addrs": self.addrs,
            "last_seen": self.last_seen,
        }

    def to_bazaar_format(self) -> dict:
        """Convert to Algorand x402 Bazaar-compatible resource listing."""
        return {
            "provider": {
                "id": self.peer_id,
                "wallet": self.eth_address,
                "endpoints": self.addrs,
            },
            "resources": [
                {
                    "type": c.service_type,
                    "price": c.price_per_call,
                    "description": c.description,
                    "payment_types": ["payment-channel", "htlc"],
                }
                for c in self.capabilities
            ],
            "last_seen": self.last_seen,
        }

    @staticmethod
    def from_dict(d: dict) -> AgentAdvertisement:
        caps = [AgentCapability.from_dict(c) for c in d.get("capabilities", [])]
        return AgentAdvertisement(
            peer_id=d["peer_id"],
            eth_address=d["eth_address"],
            capabilities=caps,
            addrs=d.get("addrs", []),
            last_seen=d.get("last_seen", time.time()),
        )
