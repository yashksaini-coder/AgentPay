"""Capability registry for agent discovery."""

from __future__ import annotations

import dataclasses
import time

import structlog

from agentic_payments.discovery.models import AgentAdvertisement

logger = structlog.get_logger(__name__)

# Agents not seen for this many seconds are pruned
STALE_THRESHOLD = 300


class CapabilityRegistry:
    """In-memory registry of known agent capabilities."""

    def __init__(self, stale_threshold: float = STALE_THRESHOLD) -> None:
        self._agents: dict[str, AgentAdvertisement] = {}  # peer_id -> ad
        self._stale_threshold = stale_threshold

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
        stale = [pid for pid, ad in self._agents.items() if ad.last_seen < cutoff]
        for pid in stale:
            del self._agents[pid]
        if stale:
            logger.info("pruned_stale_agents", count=len(stale))
        return len(stale)

    def to_bazaar_format(self) -> list[dict]:
        """Export all agents in Bazaar-compatible format."""
        self.prune_stale()
        return [ad.to_bazaar_format() for ad in self._agents.values()]
