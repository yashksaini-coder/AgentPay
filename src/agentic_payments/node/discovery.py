"""Peer discovery using libp2p's built-in mDNS and peerstore.

mDNS discovery is enabled via the host's `enable_mDNS=True` flag,
which uses zeroconf to broadcast and listen for peers on the local network.
This module wraps the host's peerstore and connected peers for a unified view.
"""

from __future__ import annotations

from typing import Any

import structlog
import trio
from libp2p.host.basic_host import BasicHost
from libp2p.peer.id import ID as PeerID
from multiaddr import Multiaddr

logger = structlog.get_logger(__name__)


class PeerDiscovery:
    """Manages peer discovery by monitoring the libp2p host's connections and peerstore.

    mDNS: Handled by the host when `enable_mDNS=True`. Discovered peers are
    automatically added to the host's peerstore.

    This class periodically polls the host for connected peers and merges
    with manually tracked peers for a unified view.
    """

    def __init__(self, host: BasicHost) -> None:
        self.host = host
        self._manually_added: dict[str, dict[str, Any]] = {}

    async def run(self, nursery: trio.Nursery) -> None:
        """Periodically poll the host for new peers discovered via mDNS/connections."""
        logger.info(
            "peer_discovery_started",
            peer_id=self.host.get_id().to_base58(),
            mdns="enabled",
        )
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
        - Manually tracked peers
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
            seen[pid_str] = {
                "peer_id": pid_str,
                "addrs": [str(a) for a in addrs],
                "connected": False,
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
                seen[pid_str] = {
                    "peer_id": pid_str,
                    "addrs": [str(a) for a in addrs],
                    "connected": True,
                }

        # 3. Manually tracked peers
        for pid_str, info in self._manually_added.items():
            if pid_str not in seen:
                seen[pid_str] = {
                    "peer_id": pid_str,
                    "addrs": info.get("addrs", []),
                    "connected": pid_str
                    in {p.to_base58() for p in self.host.get_connected_peers()},
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
