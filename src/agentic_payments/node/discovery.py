"""Peer discovery using libp2p's mDNS, bootstrap peers, and peerstore.

Discovery sources:
- mDNS: Automatic LAN peer discovery via zeroconf (enabled via host flag)
- Bootstrap peers: Explicit multiaddrs for initial network entry (WAN)
- Manual connections: Peers added via CLI/API `peer connect`
- GossipSub: Peers discovered via pubsub topic announcements

This module wraps the host's peerstore and connected peers for a unified view.
"""

from __future__ import annotations

from typing import Any

import structlog
import trio
from libp2p.host.basic_host import BasicHost
from libp2p.peer.id import ID as PeerID
from libp2p.peer.peerinfo import info_from_p2p_addr
from multiaddr import Multiaddr

logger = structlog.get_logger(__name__)


class PeerDiscovery:
    """Manages peer discovery by monitoring the libp2p host's connections and peerstore.

    Sources:
    - mDNS: Handled by the host when `enable_mDNS=True`
    - Bootstrap: Explicitly configured peer addresses for WAN connectivity
    - Manual: Peers added via API/CLI

    This class periodically polls the host for connected peers and merges
    with manually tracked peers for a unified view.
    """

    def __init__(self, host: BasicHost, bootstrap_addrs: list[str] | None = None) -> None:
        self.host = host
        self._manually_added: dict[str, dict[str, Any]] = {}
        self._bootstrap_addrs = bootstrap_addrs or []
        self._bootstrap_connected: set[str] = set()

    async def run(self, nursery: trio.Nursery) -> None:
        """Start discovery: connect to bootstrap peers, then poll for new peers."""
        logger.info(
            "peer_discovery_started",
            peer_id=self.host.get_id().to_base58(),
            mdns="enabled",
            bootstrap_count=len(self._bootstrap_addrs),
        )

        # Connect to bootstrap peers on startup
        if self._bootstrap_addrs:
            nursery.start_soon(self._connect_bootstrap_peers)

        # Periodic polling loop
        while True:
            await trio.sleep(10)
            try:
                connected = self.host.get_connected_peers()
                if connected:
                    logger.debug("connected_peers_poll", count=len(connected))
                    for pid in connected:
                        pid_str = pid.to_base58()
                        if pid_str not in self._manually_added:
                            addrs = self.host.get_peerstore().addrs(pid)
                            self._manually_added[pid_str] = {
                                "addrs": [str(a) for a in addrs],
                                "source": "mdns",
                            }
                            logger.info(
                                "peer_discovered_via_mdns",
                                peer_id=pid_str,
                                addrs=[str(a) for a in addrs],
                            )
            except Exception:
                logger.exception("peer_discovery_poll_error")

    async def _connect_bootstrap_peers(self) -> None:
        """Connect to configured bootstrap peers with retry logic."""
        for addr_str in self._bootstrap_addrs:
            try:
                maddr = Multiaddr(addr_str)
                peer_info = info_from_p2p_addr(maddr)
                pid_str = peer_info.peer_id.to_base58()

                # Skip self
                if pid_str == self.host.get_id().to_base58():
                    continue

                # Add to peerstore so the host knows how to reach this peer
                self.host.get_peerstore().add_addrs(peer_info.peer_id, peer_info.addrs, 3600)

                await self.host.connect(peer_info)
                self._bootstrap_connected.add(pid_str)
                self._manually_added[pid_str] = {
                    "addrs": [addr_str],
                    "source": "bootstrap",
                }
                logger.info(
                    "bootstrap_peer_connected",
                    peer_id=pid_str,
                    addr=addr_str,
                )
            except Exception:
                logger.warning(
                    "bootstrap_peer_failed",
                    addr=addr_str,
                    exc_info=True,
                )

        if self._bootstrap_connected:
            logger.info(
                "bootstrap_complete",
                connected=len(self._bootstrap_connected),
                total=len(self._bootstrap_addrs),
            )

    async def reconnect_bootstrap(self) -> None:
        """Reconnect to any disconnected bootstrap peers (call periodically)."""
        connected_pids = {p.to_base58() for p in self.host.get_connected_peers()}
        for addr_str in self._bootstrap_addrs:
            try:
                maddr = Multiaddr(addr_str)
                peer_info = info_from_p2p_addr(maddr)
                pid_str = peer_info.peer_id.to_base58()
                if pid_str == self.host.get_id().to_base58():
                    continue
                if pid_str not in connected_pids:
                    self.host.get_peerstore().add_addrs(peer_info.peer_id, peer_info.addrs, 3600)
                    await self.host.connect(peer_info)
                    logger.info("bootstrap_peer_reconnected", peer_id=pid_str)
            except Exception:
                pass  # Will retry on next cycle

    def on_peer_connected(self, peer_id: PeerID, addrs: list[Multiaddr]) -> None:
        """Track a manually connected peer (e.g. via CLI `peer connect`)."""
        pid_str = peer_id.to_base58()
        if pid_str not in self._manually_added:
            self._manually_added[pid_str] = {
                "addrs": [str(a) for a in addrs],
                "source": "manual",
            }
            logger.info("peer_tracked", peer_id=pid_str, source="manual")

    def get_peers(self) -> list[dict[str, Any]]:
        """Return a unified list of all known peers.

        Merges:
        - Peers from the host's peerstore (discovered via mDNS)
        - Peers from live connections
        - Manually tracked peers (including bootstrap)
        """
        seen: dict[str, dict[str, Any]] = {}

        # 1. Peerstore peers (mDNS discovered)
        peerstore = self.host.get_peerstore()
        for pid in peerstore.peer_ids():
            pid_str = pid.to_base58()
            if pid_str == self.host.get_id().to_base58():
                continue  # Skip self
            try:
                addrs = peerstore.addrs(pid)
            except Exception:
                # Peer entry expired or corrupted — skip it
                logger.debug("peerstore_addrs_skipped", peer_id=pid_str, reason="expired or error")
                continue
            source = self._manually_added.get(pid_str, {}).get("source", "mdns")
            seen[pid_str] = {
                "peer_id": pid_str,
                "addrs": [str(a) for a in addrs],
                "connected": False,
                "source": source,
            }

        # 2. Connected peers (live connections)
        for pid in self.host.get_connected_peers():
            pid_str = pid.to_base58()
            if pid_str in seen:
                seen[pid_str]["connected"] = True
            else:
                try:
                    addrs = peerstore.addrs(pid)
                except Exception:
                    addrs = []
                source = self._manually_added.get(pid_str, {}).get("source", "unknown")
                seen[pid_str] = {
                    "peer_id": pid_str,
                    "addrs": [str(a) for a in addrs],
                    "connected": True,
                    "source": source,
                }

        # 3. Manually tracked peers (bootstrap + CLI)
        for pid_str, info in self._manually_added.items():
            if pid_str not in seen:
                seen[pid_str] = {
                    "peer_id": pid_str,
                    "addrs": info.get("addrs", []),
                    "connected": pid_str
                    in {p.to_base58() for p in self.host.get_connected_peers()},
                    "source": info.get("source", "manual"),
                }

        return list(seen.values())

    @property
    def peer_count(self) -> int:
        """Total number of known peers."""
        return len(self.get_peers())

    @property
    def connected_count(self) -> int:
        """Number of currently connected peers."""
        return len(self.host.get_connected_peers())

    @property
    def bootstrap_connected_count(self) -> int:
        """Number of connected bootstrap peers."""
        connected_pids = {p.to_base58() for p in self.host.get_connected_peers()}
        return len(self._bootstrap_connected & connected_pids)
