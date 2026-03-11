"""Network topology graph built from channel announcements.

Each node is a peer_id, each edge is a payment channel with known capacity.
Used by the pathfinder to discover multi-hop routes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)

# Announcements older than this are pruned
ANNOUNCEMENT_TTL = 3600  # 1 hour


@dataclass
class ChannelEdge:
    """A directed edge in the network graph representing a payment channel."""

    channel_id: str  # hex-encoded
    peer_a: str  # peer_id
    peer_b: str  # peer_id
    capacity: int  # total deposit in wei
    last_seen: int = field(default_factory=lambda: int(time.time()))

    @property
    def available_capacity(self) -> int:
        """Approximate available capacity (we don't know exact balances of remote channels)."""
        return self.capacity


class NetworkGraph:
    """Topology graph of known payment channels across the network.

    Built from CHANNEL_ANNOUNCE gossipsub messages. Each agent maintains
    its own local view of the network topology.
    """

    def __init__(self) -> None:
        # channel_id_hex -> ChannelEdge
        self._edges: dict[str, ChannelEdge] = {}
        # peer_id -> set of channel_id_hex (adjacency list)
        self._adjacency: dict[str, set[str]] = {}

    def add_channel(
        self,
        channel_id: str,
        peer_a: str,
        peer_b: str,
        capacity: int,
    ) -> None:
        """Add or update a channel edge in the graph."""
        edge = ChannelEdge(
            channel_id=channel_id,
            peer_a=peer_a,
            peer_b=peer_b,
            capacity=capacity,
        )
        self._edges[channel_id] = edge

        # Bidirectional adjacency
        self._adjacency.setdefault(peer_a, set()).add(channel_id)
        self._adjacency.setdefault(peer_b, set()).add(channel_id)

        logger.debug(
            "graph_channel_added",
            channel_id=channel_id[:16],
            peer_a=peer_a[:12],
            peer_b=peer_b[:12],
            capacity=capacity,
        )

    def remove_channel(self, channel_id: str) -> None:
        """Remove a channel edge from the graph."""
        edge = self._edges.pop(channel_id, None)
        if edge is None:
            return
        self._adjacency.get(edge.peer_a, set()).discard(channel_id)
        self._adjacency.get(edge.peer_b, set()).discard(channel_id)

    def get_neighbors(self, peer_id: str) -> list[tuple[str, ChannelEdge]]:
        """Get all neighbors of a peer with their connecting channel edges.

        Returns: list of (neighbor_peer_id, edge)
        """
        result = []
        for cid in self._adjacency.get(peer_id, set()):
            edge = self._edges.get(cid)
            if edge is None:
                continue
            neighbor = edge.peer_b if edge.peer_a == peer_id else edge.peer_a
            result.append((neighbor, edge))
        return result

    def get_edge(self, channel_id: str) -> ChannelEdge | None:
        """Get a channel edge by ID."""
        return self._edges.get(channel_id)

    def has_peer(self, peer_id: str) -> bool:
        """Check if a peer exists in the graph."""
        return peer_id in self._adjacency

    def peer_count(self) -> int:
        """Number of known peers in the graph."""
        return len(self._adjacency)

    def channel_count(self) -> int:
        """Number of known channels in the graph."""
        return len(self._edges)

    def prune_stale(self) -> int:
        """Remove channels not seen within the TTL. Returns count removed."""
        now = int(time.time())
        stale = [
            cid for cid, edge in self._edges.items()
            if now - edge.last_seen > ANNOUNCEMENT_TTL
        ]
        for cid in stale:
            self.remove_channel(cid)
        if stale:
            logger.info("graph_pruned_stale", count=len(stale))
        return len(stale)

    def to_dict(self) -> dict:
        """Serialize graph for API responses."""
        return {
            "peers": list(self._adjacency.keys()),
            "channels": [
                {
                    "channel_id": e.channel_id,
                    "peer_a": e.peer_a,
                    "peer_b": e.peer_b,
                    "capacity": e.capacity,
                }
                for e in self._edges.values()
            ],
            "peer_count": self.peer_count(),
            "channel_count": self.channel_count(),
        }
