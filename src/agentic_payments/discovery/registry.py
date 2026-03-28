"""Capability registry for agent discovery."""

from __future__ import annotations

import dataclasses
import hashlib
import os
import time

import structlog

from agentic_payments.discovery.models import AgentAdvertisement, AgentCapability

logger = structlog.get_logger(__name__)

# Agents not seen for this many seconds are pruned
STALE_THRESHOLD = int(os.environ.get("STALE_THRESHOLD", "300"))

_CapDict = dict[str, str | int]
_ProfileDict = dict[str, str | list[_CapDict]]

# Demo agent profiles for seeding the discovery registry
_DEMO_PROFILES: list[_ProfileDict] = [
    {
        "label": "B",
        "role": "worker",
        "capabilities": [
            {
                "service_type": "llm-inference",
                "price_per_call": 50000,
                "description": "GPT-4 inference endpoint",
            },
        ],
    },
    {
        "label": "C",
        "role": "data_provider",
        "capabilities": [
            {
                "service_type": "data-retrieval",
                "price_per_call": 10000,
                "description": "Indexed blockchain data",
            },
            {
                "service_type": "ipfs-pinning",
                "price_per_call": 25000,
                "description": "IPFS pin & retrieve",
            },
        ],
    },
    {
        "label": "D",
        "role": "validator",
        "capabilities": [
            {
                "service_type": "proof-verification",
                "price_per_call": 30000,
                "description": "ZK proof validation",
            },
        ],
    },
    {
        "label": "E",
        "role": "gateway",
        "capabilities": [
            {
                "service_type": "api-gateway",
                "price_per_call": 5000,
                "description": "Rate-limited API proxy",
            },
            {
                "service_type": "image-gen",
                "price_per_call": 100000,
                "description": "Stable Diffusion XL",
            },
        ],
    },
]


def _deterministic_peer_id(seed: str) -> str:
    """Generate a deterministic base58-like peer ID from a seed string."""
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"12D3KooW{h[:40]}"


def _deterministic_eth_address(seed: str) -> str:
    """Generate a deterministic ETH address from a seed string."""
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"0x{h[:40]}"


class CapabilityRegistry:
    """In-memory registry of known agent capabilities."""

    def __init__(self, stale_threshold: float = STALE_THRESHOLD) -> None:
        self._agents: dict[str, AgentAdvertisement] = {}  # peer_id -> ad
        self._stale_threshold = stale_threshold
        self._pinned: set[str] = set()  # peer_ids exempt from pruning

    def seed_demo_agents(self, own_peer_id: str = "") -> int:
        """Register demo agents for showcase. Pins own node too. Returns count seeded."""
        if not os.environ.get("SEED_DEMO_AGENTS"):
            return 0
        # Pin the real node so it never gets pruned
        if own_peer_id:
            self._pinned.add(own_peer_id)
        count = 0
        for profile in _DEMO_PROFILES:
            seed = f"agentpay-demo-{profile['label']}"
            peer_id = _deterministic_peer_id(seed)
            eth_address = _deterministic_eth_address(seed)
            cap_list: list[_CapDict] = profile["capabilities"]  # type: ignore[assignment]
            role = str(profile["role"])
            caps = [
                AgentCapability(
                    service_type=str(c["service_type"]),
                    price_per_call=int(c["price_per_call"]),
                    description=str(c["description"]),
                    role=role,
                )
                for c in cap_list
            ]
            ad = AgentAdvertisement(
                peer_id=peer_id,
                eth_address=eth_address,
                capabilities=caps,
                addrs=[],
                last_seen=time.time() + 999_999_999,  # never pruned
            )
            self._agents[peer_id] = ad
            self._pinned.add(peer_id)
            count += 1
        logger.info("seeded_demo_agents", count=count)
        return count

    def register(self, ad: AgentAdvertisement) -> None:
        """Register or update an agent advertisement."""
        ad = dataclasses.replace(ad, last_seen=time.time())
        self._agents[ad.peer_id] = ad
        logger.debug("agent_registered", peer_id=ad.peer_id, caps=len(ad.capabilities))

    def unregister(self, peer_id: str) -> None:
        """Remove an agent from the registry."""
        self._agents.pop(peer_id, None)

    def search(self, capability: str | None = None) -> list[AgentAdvertisement]:
        """Search for agents, optionally filtered by capability service_type."""
        self.prune_stale()
        if capability is None:
            return list(self._agents.values())
        return [
            ad
            for ad in self._agents.values()
            if any(c.service_type == capability for c in ad.capabilities)
        ]

    def get(self, peer_id: str) -> AgentAdvertisement | None:
        """Get a specific agent's advertisement."""
        return self._agents.get(peer_id)

    def prune_stale(self) -> int:
        """Remove agents not seen within the stale threshold. Returns count pruned."""
        cutoff = time.time() - self._stale_threshold
        stale = [
            pid
            for pid, ad in self._agents.items()
            if ad.last_seen < cutoff and pid not in self._pinned
        ]
        for pid in stale:
            del self._agents[pid]
        if stale:
            logger.info("pruned_stale_agents", count=len(stale))
        return len(stale)

    def to_bazaar_format(self) -> list[dict]:
        """Export all agents in Bazaar-compatible format."""
        self.prune_stale()
        return [ad.to_bazaar_format() for ad in self._agents.values()]
