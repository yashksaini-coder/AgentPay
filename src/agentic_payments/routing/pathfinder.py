"""BFS pathfinder for multi-hop payment routes.

Finds the shortest path through the network graph that has sufficient
capacity at every hop to forward the payment amount.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from agentic_payments.routing.graph import ChannelEdge, NetworkGraph

# Time delta subtracted from timeout at each hop (seconds)
TIMEOUT_DELTA = 120


@dataclass
class RouteHop:
    """A single hop in a payment route."""

    peer_id: str  # Next peer to forward to
    channel_id: str  # Channel to use for this hop
    amount: int  # Amount to forward (may include fees later)
    timeout: int  # HTLC timeout for this hop


@dataclass
class Route:
    """A complete multi-hop payment route from source to destination."""

    hops: list[RouteHop]
    total_amount: int
    total_timeout: int

    @property
    def hop_count(self) -> int:
        return len(self.hops)

    def to_dict(self) -> dict:
        return {
            "hops": [
                {
                    "peer_id": h.peer_id,
                    "channel_id": h.channel_id,
                    "amount": h.amount,
                    "timeout": h.timeout,
                }
                for h in self.hops
            ],
            "total_amount": self.total_amount,
            "total_timeout": self.total_timeout,
            "hop_count": self.hop_count,
        }


def find_route(
    graph: NetworkGraph,
    source: str,
    destination: str,
    amount: int,
    base_timeout: int,
    max_hops: int = 10,
) -> Route | None:
    """Find a route from source to destination using BFS.

    Returns the shortest path where every channel has >= `amount` capacity.
    Returns None if no route exists.

    Args:
        graph: Network topology graph
        source: Source peer_id
        destination: Destination peer_id
        amount: Payment amount in wei
        base_timeout: Starting HTLC timeout (absolute unix timestamp)
        max_hops: Maximum number of hops allowed
    """
    if source == destination:
        return None

    # BFS: queue of (current_peer, path_so_far)
    queue: deque[tuple[str, list[tuple[str, ChannelEdge]]]] = deque()
    queue.append((source, []))
    visited: set[str] = {source}

    while queue:
        current, path = queue.popleft()

        if len(path) >= max_hops:
            continue

        for neighbor, edge in graph.get_neighbors(current):
            if neighbor in visited:
                continue

            # Check capacity
            if edge.available_capacity < amount:
                continue

            new_path = path + [(neighbor, edge)]

            if neighbor == destination:
                return _build_route(new_path, amount, base_timeout)

            visited.add(neighbor)
            queue.append((neighbor, new_path))

    return None


def _build_route(
    path: list[tuple[str, ChannelEdge]],
    amount: int,
    base_timeout: int,
) -> Route:
    """Convert a BFS path into a Route with timeouts decreasing per hop.

    The first hop gets the highest timeout, each subsequent hop gets
    TIMEOUT_DELTA less — ensuring the sender's HTLC expires last.
    """
    hops = []
    for i, (peer_id, edge) in enumerate(path):
        timeout = base_timeout - (i * TIMEOUT_DELTA)
        hops.append(RouteHop(
            peer_id=peer_id,
            channel_id=edge.channel_id,
            amount=amount,
            timeout=timeout,
        ))

    return Route(
        hops=hops,
        total_amount=amount,
        total_timeout=base_timeout,
    )
