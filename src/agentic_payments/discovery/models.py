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

    def to_bazaar_format(self, network: str = "ethereum-sepolia") -> dict:
        """Convert to x402 Bazaar-compatible resource listing.

        Follows the Bazaar discovery layer spec for agent service
        cataloging. Compatible with Algorand x402, Coinbase x402,
        and Filecoin facilitators.
        """
        return {
            "provider": {
                "id": self.peer_id,
                "wallet": self.eth_address,
                "network": network,
                "endpoints": self.addrs,
            },
            "resources": [
                {
                    "scheme": "exact",
                    "network": network,
                    "maxAmountRequired": str(c.price_per_call),
                    "payTo": self.eth_address,
                    "asset": "native",
                    "resource": f"/services/{c.service_type}",
                    "description": c.description,
                    "mimeType": "application/json",
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
