"""AgentNode: central orchestrator for a payment-capable libp2p agent."""

from __future__ import annotations

import time
from typing import Any

import structlog
import trio
from libp2p import new_host
from libp2p.custom_types import TProtocol
from libp2p.host.basic_host import BasicHost
from libp2p.network.stream.net_stream import NetStream
from libp2p.tools.async_service.trio_service import background_trio_service
from libp2p.peer.id import ID as PeerID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from multiaddr import Multiaddr

from agentic_payments.chain.wallet import Wallet
from agentic_payments.config import Settings
from agentic_payments.node.discovery import PeerDiscovery
from agentic_payments.node.identity import load_or_generate_identity, peer_id_from_keypair
from agentic_payments.payments.channel import PaymentChannel
from agentic_payments.payments.manager import ChannelManager
from agentic_payments.payments.voucher import SignedVoucher
from agentic_payments.protocol.codec import read_message, write_message
from agentic_payments.protocol.handler import PROTOCOL_ID, PaymentProtocolHandler
from agentic_payments.protocol.messages import (
    HtlcPropose,
    MessageType,
    PaymentClose,
    PaymentOpen,
    from_wire,
    to_wire,
)
from agentic_payments.pubsub.broadcaster import PubsubBroadcaster
from agentic_payments.pubsub.topics import TOPIC_AGENT_DISCOVERY, TOPIC_CHANNEL_ANNOUNCEMENTS
from agentic_payments.routing.graph import NetworkGraph
from agentic_payments.routing.htlc import (
    HtlcManager,
    PendingHtlc,
    generate_preimage,
    verify_preimage,
)
from agentic_payments.routing.pathfinder import Route, find_route

logger = structlog.get_logger(__name__)

# GossipSub protocol versions supported
GOSSIPSUB_PROTOCOLS = [
    TProtocol("/meshsub/1.0.0"),
    TProtocol("/meshsub/1.1.0"),
    TProtocol("/meshsub/1.2.0"),
]


class AgentNode:
    """A payment-capable agent node on the libp2p network.

    Creates a libp2p host with:
    - Noise security (default)
    - Yamux stream muxing
    - mDNS peer discovery
    - GossipSub pubsub for capability advertising and receipts
    - Custom payment protocol handler on streams
    """

    def __init__(self, config: Settings) -> None:
        self.config = config
        self.host: BasicHost | None = None
        self.peer_id: PeerID | None = None
        self.wallet: Wallet | None = None
        self.channel_manager: ChannelManager | None = None
        self.discovery: PeerDiscovery | None = None
        self.protocol_handler: PaymentProtocolHandler | None = None
        self.pubsub: Pubsub | None = None
        self.gossipsub: GossipSub | None = None
        self.broadcaster: PubsubBroadcaster | None = None
        self.network_graph: NetworkGraph = NetworkGraph()
        self.htlc_manager: HtlcManager = HtlcManager()
        self.listen_addrs: list[str] = []
        self._nursery: trio.Nursery | None = None
        self._streams: dict[str, NetStream] = {}
        self._stream_locks: dict[str, trio.Lock] = {}
        # Preimages we generated (for payments we initiated)
        self._preimages: dict[bytes, bytes] = {}  # payment_hash -> preimage

    def _require_started(self) -> None:
        """Guard: ensure the node has been started."""
        if self.host is None or self.wallet is None or self.channel_manager is None:
            raise RuntimeError("AgentNode not started — call start() first")

    async def start(self, nursery: trio.Nursery) -> None:
        """Start the agent node.

        1. Load/generate Ed25519 identity
        2. Create libp2p host with mDNS, Noise security, Yamux muxing
        3. Register payment protocol stream handler
        4. Initialize GossipSub pubsub and subscribe to topics
        5. Start peer discovery
        6. Start REST API server
        """
        self._nursery = nursery

        # --- Identity ---
        key_pair = load_or_generate_identity(self.config.node.identity_path)
        self.peer_id = peer_id_from_keypair(key_pair)

        # --- Ethereum wallet ---
        self.wallet = Wallet.generate()
        self.channel_manager = ChannelManager(self.wallet.address)
        self.protocol_handler = PaymentProtocolHandler(
            channel_manager=self.channel_manager,
            htlc_manager=self.htlc_manager,
            on_htlc_propose=self._on_htlc_propose,
            on_htlc_fulfill=self._on_htlc_fulfill,
            on_htlc_cancel=self._on_htlc_cancel,
            on_channel_opened=self._on_channel_accepted,
        )

        # --- libp2p host ---
        self.host = new_host(
            key_pair=key_pair,
            muxer_preference="YAMUX",
            enable_mDNS=self.config.node.enable_mdns,
        )

        # --- Register payment protocol ---
        self.host.set_stream_handler(
            TProtocol(PROTOCOL_ID),
            self._handle_incoming_stream,
        )

        # --- Listen addresses ---
        listen_addrs = [
            Multiaddr(f"/ip4/0.0.0.0/tcp/{self.config.node.port}"),
        ]
        if self.config.node.ws_port:
            listen_addrs.append(Multiaddr(f"/ip4/0.0.0.0/tcp/{self.config.node.ws_port}/ws"))

        # --- Start host ---
        async with self.host.run(listen_addrs=listen_addrs):
            self.listen_addrs = [str(addr) for addr in self.host.get_addrs()]
            logger.info(
                "agent_node_started",
                peer_id=self.peer_id.to_base58(),
                addrs=self.listen_addrs,
                eth_address=self.wallet.address,
            )

            # --- GossipSub pubsub ---
            self.gossipsub = GossipSub(
                protocols=GOSSIPSUB_PROTOCOLS,
                degree=8,
                degree_low=6,
                degree_high=12,
                heartbeat_interval=120,
            )
            self.pubsub = Pubsub(
                host=self.host,
                router=self.gossipsub,
                strict_signing=True,
            )
            self.broadcaster = PubsubBroadcaster(self.pubsub)

            # Run pubsub as an async service
            nursery.start_soon(self._run_pubsub)

            # --- Peer discovery (with bootstrap peers) ---
            self.discovery = PeerDiscovery(
                self.host,
                bootstrap_addrs=self.config.node.bootstrap_peers,
            )
            nursery.start_soon(self.discovery.run, nursery)

            # --- REST API ---
            from agentic_payments.api.server import serve_api

            await nursery.start(serve_api, self.config.api, self)

            # Block until cancelled
            await trio.sleep_forever()

    async def _run_pubsub(self) -> None:
        """Run the GossipSub pubsub service and subscribe to all topics."""
        try:
            async with background_trio_service(self.pubsub):
                await self.broadcaster.subscribe_all()

                # Announce ourselves on the discovery topic
                await self.broadcaster.publish(
                    TOPIC_AGENT_DISCOVERY,
                    {
                        "type": "announce",
                        "peer_id": self.peer_id.to_base58(),
                        "eth_address": self.wallet.address,
                        "addrs": self.listen_addrs,
                    },
                )

                # Register channel announcement handler for routing
                self.broadcaster.on_message(
                    TOPIC_CHANNEL_ANNOUNCEMENTS,
                    self._handle_channel_announce,
                )

                # Sync existing local channels into the routing graph
                self._sync_graph_from_channels()

                # Announce all existing active channels on gossipsub
                for ch in self.channel_manager.list_channels():
                    if ch.state.name in ("ACTIVE", "OPEN"):
                        await self.broadcaster.broadcast_channel({
                            "channel_id": ch.channel_id.hex(),
                            "peer_a": self.peer_id.to_base58(),
                            "peer_b": ch.peer_id,
                            "capacity": ch.total_deposit,
                        })

                # Run listeners for incoming pubsub messages
                await self.broadcaster.run(self._nursery)

                # Keep the pubsub service alive until cancelled
                await trio.sleep_forever()
        except Exception:
            logger.exception("pubsub_service_error")
            raise

    async def _handle_incoming_stream(self, stream: NetStream) -> None:
        """Handle an incoming payment protocol stream from a remote peer."""
        await self.protocol_handler.handle_stream(stream)

    async def stop(self) -> None:
        """Stop the agent node."""
        logger.info("agent_node_stopping", peer_id=str(self.peer_id))
        if self.host:
            await self.host.close()

    # ------------------------------------------------------------------
    # Peer management (uses libp2p host directly)
    # ------------------------------------------------------------------

    async def connect(self, peer_multiaddr: str) -> None:
        """Connect to a peer by multiaddr string."""
        self._require_started()
        maddr = Multiaddr(peer_multiaddr)
        peer_info = info_from_p2p_addr(maddr)
        await self.host.connect(peer_info)

        if self.discovery:
            self.discovery.on_peer_connected(
                peer_id=peer_info.peer_id,
                addrs=[maddr],
            )
        logger.info("peer_connected", peer_id=str(peer_info.peer_id), addr=peer_multiaddr)

    def get_connected_peers(self) -> list[PeerID]:
        """Get currently connected peer IDs from the libp2p host."""
        if self.host is None:
            return []
        return self.host.get_connected_peers()

    async def disconnect(self, peer_id: str) -> None:
        """Disconnect from a peer and clean up cached streams."""
        self._require_started()
        pid = PeerID.from_base58(peer_id)
        await self.host.disconnect(pid)
        # Clean up cached stream for this peer
        self._streams.pop(peer_id, None)
        logger.info("peer_disconnected", peer_id=peer_id)

    # ------------------------------------------------------------------
    # Stream management
    # ------------------------------------------------------------------

    def _get_stream_lock(self, peer_id: str) -> trio.Lock:
        """Get or create a per-peer lock for serializing stream I/O."""
        lock = self._stream_locks.get(peer_id)
        if lock is None:
            lock = trio.Lock()
            self._stream_locks[peer_id] = lock
        return lock

    def _evict_stream(self, peer_id: str) -> None:
        """Remove a cached stream for a peer (e.g. on error or disconnect)."""
        self._streams.pop(peer_id, None)

    async def _get_or_open_stream(self, peer_id: str) -> NetStream:
        """Get an existing stream or open a new one. Evicts stale streams on error."""
        stream = self._streams.get(peer_id)
        if stream is not None:
            return stream
        stream = await self._open_stream(peer_id)
        self._streams[peer_id] = stream
        return stream

    async def _open_stream(self, peer_id: str) -> NetStream:
        """Open a new payment protocol stream to a peer via the libp2p host."""
        self._require_started()
        pid = PeerID.from_base58(peer_id)
        stream = await self.host.new_stream(pid, [TProtocol(PROTOCOL_ID)])
        return stream

    # ------------------------------------------------------------------
    # Payment channel operations
    # ------------------------------------------------------------------

    async def open_payment_channel(
        self,
        peer_id: str,
        receiver: str,
        deposit: int,
    ) -> PaymentChannel:
        """Open a payment channel with a connected peer.

        Opens a new libp2p stream, sends a PaymentOpen, waits for ACK.
        Cleans up channel on failure.
        """
        self._require_started()
        msg = PaymentOpen.new(
            sender=self.wallet.address,
            receiver=receiver,
            total_deposit=deposit,
        )

        channel = self.channel_manager.create_channel(
            channel_id=msg.channel_id,
            receiver=receiver,
            total_deposit=deposit,
            peer_id=peer_id,
        )

        lock = self._get_stream_lock(peer_id)
        try:
            async with lock:
                stream = await self._open_stream(peer_id)
                await write_message(stream, to_wire(MessageType.PAYMENT_OPEN, msg))

                # Wait for ACK
                raw = await read_message(stream)
            _, ack = from_wire(raw)
            if ack.status == "accepted":
                channel.accept()
                channel.activate()
                self._streams[peer_id] = stream
                logger.info("channel_opened", channel_id=msg.channel_id.hex()[:16])
            else:
                self.channel_manager.remove_channel(msg.channel_id)
                raise RuntimeError(f"Channel open rejected: {ack.reason}")
        except RuntimeError:
            raise
        except Exception:
            # Clean up orphaned channel on any failure
            self.channel_manager.remove_channel(msg.channel_id)
            raise

        # Announce channel on gossipsub for routing topology
        await self._announce_channel(channel)

        return channel

    async def pay(self, channel_id: bytes, amount: int) -> SignedVoucher:
        """Send a micropayment voucher on an existing channel.

        Creates a signed voucher, sends it, waits for ACK.
        Evicts stale streams on error and retries once.
        Uses per-peer lock to prevent concurrent stream corruption.
        """
        self._require_started()
        channel = self.channel_manager.get_channel(channel_id)
        peer_id = channel.peer_id
        lock = self._get_stream_lock(peer_id)

        async def _attempt_pay() -> SignedVoucher:
            async with lock:
                stream = await self._get_or_open_stream(peer_id)

                async def send_fn(msg):
                    await write_message(stream, to_wire(MessageType.PAYMENT_UPDATE, msg))

                voucher = await self.channel_manager.send_payment(
                    channel_id=channel_id,
                    amount=amount,
                    private_key=self.wallet.private_key,
                    send_fn=send_fn,
                )

                raw = await read_message(stream)
                msg_type, ack = from_wire(raw)
                if msg_type == MessageType.HTLC_CANCEL:
                    raise RuntimeError(f"Payment rejected (HTLC cancel): {ack.reason}")
                if msg_type != MessageType.PAYMENT_ACK:
                    raise RuntimeError(f"Unexpected response type: {msg_type}")
                if ack.status != "accepted":
                    raise RuntimeError(f"Payment rejected: {ack.reason}")

                return voucher

        try:
            return await _attempt_pay()
        except (ConnectionError, OSError):
            # Stream may be stale — evict and retry once
            self._evict_stream(peer_id)
            logger.warning("pay_stream_error_retrying", peer_id=peer_id)
            return await _attempt_pay()

    async def close_channel(self, channel_id: bytes) -> None:
        """Cooperatively close a payment channel.

        Sends a PaymentClose over the stream and transitions state on ACK.
        Cleans up the stream cache after closing.
        """
        self._require_started()
        channel = self.channel_manager.get_channel(channel_id)
        peer_id = channel.peer_id

        msg = PaymentClose(
            channel_id=channel_id,
            final_nonce=channel.nonce,
            final_amount=channel.total_paid,
            cooperative=True,
        )

        lock = self._get_stream_lock(peer_id)
        async with lock:
            stream = await self._get_or_open_stream(peer_id)
            await write_message(stream, to_wire(MessageType.PAYMENT_CLOSE, msg))
            raw = await read_message(stream)
        _, ack = from_wire(raw)

        if ack.status == "accepted":
            channel.cooperative_close()
            channel.settle()
            # Clean up stream for this peer
            self._evict_stream(peer_id)
            logger.info("channel_closed", channel_id=channel_id.hex()[:16])

            # Broadcast receipt on gossipsub
            if self.broadcaster:
                await self.broadcaster.broadcast_receipt(
                    {
                        "channel_id": channel_id.hex(),
                        "sender": channel.sender,
                        "receiver": channel.receiver,
                        "total_paid": channel.total_paid,
                        "nonce": channel.nonce,
                    }
                )
        else:
            raise RuntimeError(f"Channel close rejected: {ack.reason}")

    # ------------------------------------------------------------------
    # Multi-hop routing
    # ------------------------------------------------------------------

    async def _announce_channel(self, channel: PaymentChannel) -> None:
        """Announce a channel on gossipsub for routing topology."""
        if not self.broadcaster:
            return
        # Also add to our own graph
        self.network_graph.add_channel(
            channel_id=channel.channel_id.hex(),
            peer_a=self.peer_id.to_base58(),
            peer_b=channel.peer_id,
            capacity=channel.total_deposit,
        )
        await self.broadcaster.broadcast_channel({
            "channel_id": channel.channel_id.hex(),
            "peer_a": self.peer_id.to_base58(),
            "peer_b": channel.peer_id,
            "capacity": channel.total_deposit,
        })

    async def _on_channel_accepted(self, channel: PaymentChannel) -> None:
        """Called when we accept an incoming channel (receiver side)."""
        await self._announce_channel(channel)

    def _sync_graph_from_channels(self) -> None:
        """Populate the network graph from all existing local channels."""
        if not self.channel_manager or not self.peer_id:
            return
        for ch in self.channel_manager.list_channels():
            if ch.state.name in ("ACTIVE", "OPEN"):
                self.network_graph.add_channel(
                    channel_id=ch.channel_id.hex(),
                    peer_a=self.peer_id.to_base58(),
                    peer_b=ch.peer_id,
                    capacity=ch.total_deposit,
                )

    async def _handle_channel_announce(self, data: dict, from_peer: PeerID) -> None:
        """Handle a channel announcement from gossipsub."""
        info = data.get("data", data)
        cid = info.get("channel_id")
        peer_a = info.get("peer_a")
        peer_b = info.get("peer_b")
        capacity = info.get("capacity")
        if cid and peer_a and peer_b and capacity:
            self.network_graph.add_channel(cid, peer_a, peer_b, capacity)

    def find_route(self, destination: str, amount: int) -> Route | None:
        """Find a multi-hop route to a destination peer."""
        self._require_started()
        import time
        base_timeout = int(time.time()) + 600  # 10 minute base timeout
        return find_route(
            graph=self.network_graph,
            source=self.peer_id.to_base58(),
            destination=destination,
            amount=amount,
            base_timeout=base_timeout,
        )

    async def route_payment(
        self, destination: str, amount: int
    ) -> dict:
        """Send a multi-hop payment to a destination peer.

        1. Generate preimage + payment_hash
        2. Find route via BFS
        3. Send HTLC to first hop
        4. Wait for fulfill to propagate back
        """
        self._require_started()
        route = self.find_route(destination, amount)
        if route is None:
            raise RuntimeError(f"No route found to {destination} for amount {amount}")

        if route.hop_count == 0:
            raise RuntimeError("Route has no hops")

        # Generate preimage (only the sender and final receiver know it)
        preimage, payment_hash = generate_preimage()
        self._preimages[payment_hash] = preimage

        # Find the channel to the first hop
        first_hop = route.hops[0]
        channel = self._find_channel_to_peer(first_hop.peer_id)
        if channel is None:
            raise RuntimeError(f"No channel to first hop {first_hop.peer_id}")

        # Lock funds on our channel
        channel.lock_htlc(amount)

        # Build onion routing data (simplified: plaintext)
        # The final hop entry includes the preimage so the receiver can fulfill.
        import msgpack
        if route.hop_count > 1:
            remaining = [
                {"peer_id": h.peer_id, "channel_id": h.channel_id, "amount": h.amount, "timeout": h.timeout}
                for h in route.hops[1:]
            ]
            # Attach preimage to the last hop so final destination can reveal it
            remaining[-1]["preimage"] = preimage
            onion_next = msgpack.packb(remaining, use_bin_type=True)
        else:
            # Single hop — we are sending directly to the final destination.
            # Include preimage so the receiver can fulfill the HTLC.
            onion_next = msgpack.packb([{"preimage": preimage}], use_bin_type=True)

        # Create and track the outgoing HTLC
        htlc_msg = HtlcPropose(
            channel_id=channel.channel_id,
            payment_hash=payment_hash,
            amount=amount,
            timeout=first_hop.timeout,
            onion_next=onion_next,
        )

        outgoing_htlc = PendingHtlc(
            htlc_id=htlc_msg.htlc_id,
            channel_id=channel.channel_id,
            payment_hash=payment_hash,
            amount=amount,
            timeout=first_hop.timeout,
        )
        self.htlc_manager.add_htlc(outgoing_htlc)

        # Send HTLC to first hop (lock serializes all stream I/O per peer)
        peer_id = first_hop.peer_id
        lock = self._get_stream_lock(peer_id)

        async with lock:
            stream = await self._get_or_open_stream(peer_id)
            await write_message(stream, to_wire(MessageType.HTLC_PROPOSE, htlc_msg))

            # Wait for fulfill or cancel response
            raw = await read_message(stream)
            msg_type, resp = from_wire(raw)

            if msg_type == MessageType.HTLC_FULFILL:
                if verify_preimage(resp.preimage, payment_hash):
                    self.htlc_manager.fulfill(outgoing_htlc.htlc_id, resp.preimage)
                    channel.unlock_htlc(amount)
                    # Actually transfer the funds via a voucher
                    async def send_fn(msg):
                        await write_message(stream, to_wire(MessageType.PAYMENT_UPDATE, msg))
                    await self.channel_manager.send_payment(
                        channel_id=channel.channel_id,
                        amount=amount,
                        private_key=self.wallet.private_key,
                        send_fn=send_fn,
                    )
                    # Read the PAYMENT_ACK response (prevents stream buffer offset)
                    raw = await read_message(stream)
                    ack_type, ack = from_wire(raw)
                    if ack_type != MessageType.PAYMENT_ACK:
                        raise RuntimeError(f"Unexpected voucher ACK type: {ack_type}")
                    if ack.status != "accepted":
                        raise RuntimeError(f"Voucher rejected by peer: {ack.reason}")
                else:
                    channel.unlock_htlc(amount)
                    self.htlc_manager.cancel(outgoing_htlc.htlc_id, "Invalid preimage")
                    raise RuntimeError("Received invalid preimage")

            elif msg_type == MessageType.HTLC_CANCEL:
                channel.unlock_htlc(amount)
                self.htlc_manager.cancel(outgoing_htlc.htlc_id, resp.reason)
                raise RuntimeError(f"HTLC cancelled: {resp.reason}")

            else:
                channel.unlock_htlc(amount)
                raise RuntimeError(f"Unexpected response type: {msg_type}")

        if msg_type == MessageType.HTLC_FULFILL and verify_preimage(resp.preimage, payment_hash):
            logger.info(
                "routed_payment_complete",
                destination=destination,
                amount=amount,
                hops=route.hop_count,
            )
            return {
                "status": "fulfilled",
                "payment_hash": payment_hash.hex(),
                "preimage": resp.preimage.hex(),
                "route": route.to_dict(),
                "amount": amount,
            }

    def _find_channel_to_peer(self, peer_id: str) -> PaymentChannel | None:
        """Find an active channel to a specific peer where we are the sender."""
        local_addr = self.wallet.address if self.wallet else ""
        # Prefer channels where we are the sender (can pay out)
        for ch in self.channel_manager.list_channels():
            if ch.peer_id == peer_id and ch.state.name == "ACTIVE" and ch.sender == local_addr:
                return ch
        return None

    # ------------------------------------------------------------------
    # HTLC callbacks (called by protocol handler)
    # ------------------------------------------------------------------

    async def _on_htlc_propose(
        self, msg: Any, remote_peer: str
    ) -> tuple[MessageType, Any]:
        """Handle incoming HTLC proposal — either forward or settle as final hop."""
        from agentic_payments.protocol.messages import HtlcCancel, HtlcFulfill, HtlcPropose
        from agentic_payments.routing.pathfinder import TIMEOUT_DELTA

        # Validate timeout: must be in the future with enough margin
        now = int(time.time())
        if msg.timeout <= now:
            logger.warning("htlc_expired_on_arrival", htlc_id=msg.htlc_id.hex()[:16], timeout=msg.timeout)
            return MessageType.HTLC_CANCEL, HtlcCancel(
                channel_id=msg.channel_id,
                htlc_id=msg.htlc_id,
                reason="HTLC timeout already expired",
            )

        # Create the incoming HTLC record
        incoming = PendingHtlc(
            htlc_id=msg.htlc_id,
            channel_id=msg.channel_id,
            payment_hash=msg.payment_hash,
            amount=msg.amount,
            timeout=msg.timeout,
            onion_next=msg.onion_next,
        )
        self.htlc_manager.add_htlc(incoming)

        # Decode onion data to check if we're the final hop
        import msgpack
        onion_hops = []
        if msg.onion_next:
            try:
                onion_hops = msgpack.unpackb(msg.onion_next, raw=False)
            except Exception:
                pass

        # Final hop: no onion data, or onion has a single entry with preimage (no peer_id)
        is_final = (not onion_hops) or (
            len(onion_hops) == 1 and "preimage" in onion_hops[0] and "peer_id" not in onion_hops[0]
        )

        if is_final:
            # Extract preimage from onion data or local store
            preimage = self._preimages.get(msg.payment_hash)
            if preimage is None and onion_hops:
                # Preimage delivered via onion from the sender
                raw_pre = onion_hops[0].get("preimage") if onion_hops else None
                if raw_pre and isinstance(raw_pre, bytes) and verify_preimage(raw_pre, msg.payment_hash):
                    preimage = raw_pre
            if preimage is not None:
                self.htlc_manager.fulfill(msg.htlc_id, preimage)
                return MessageType.HTLC_FULFILL, HtlcFulfill(
                    channel_id=msg.channel_id,
                    htlc_id=msg.htlc_id,
                    preimage=preimage,
                )
            else:
                self.htlc_manager.cancel(msg.htlc_id, "Unknown payment hash")
                return MessageType.HTLC_CANCEL, HtlcCancel(
                    channel_id=msg.channel_id,
                    htlc_id=msg.htlc_id,
                    reason="Unknown payment hash at final destination",
                )

        # We are an intermediate hop — forward using already-decoded onion_hops
        remaining_hops = onion_hops

        next_hop = remaining_hops[0]
        next_peer_id = next_hop["peer_id"]

        # Validate CLTV delta: incoming timeout must leave enough room for outgoing
        outgoing_timeout = next_hop.get("timeout", msg.timeout - TIMEOUT_DELTA)
        if msg.timeout - outgoing_timeout < TIMEOUT_DELTA:
            self.htlc_manager.cancel(msg.htlc_id, "Insufficient CLTV delta")
            logger.warning(
                "htlc_insufficient_cltv",
                incoming_timeout=msg.timeout,
                outgoing_timeout=outgoing_timeout,
                delta=TIMEOUT_DELTA,
            )
            return MessageType.HTLC_CANCEL, HtlcCancel(
                channel_id=msg.channel_id,
                htlc_id=msg.htlc_id,
                reason=f"Insufficient timeout delta (need {TIMEOUT_DELTA}s, got {msg.timeout - outgoing_timeout}s)",
            )

        # Find channel to next peer
        next_channel = self._find_channel_to_peer(next_peer_id)
        if next_channel is None:
            self.htlc_manager.cancel(msg.htlc_id, f"No channel to {next_peer_id}")
            return MessageType.HTLC_CANCEL, HtlcCancel(
                channel_id=msg.channel_id,
                htlc_id=msg.htlc_id,
                reason="No channel to next hop",
            )

        # Lock funds on our outgoing channel
        try:
            next_channel.lock_htlc(msg.amount)
        except Exception as e:
            self.htlc_manager.cancel(msg.htlc_id, str(e))
            return MessageType.HTLC_CANCEL, HtlcCancel(
                channel_id=msg.channel_id,
                htlc_id=msg.htlc_id,
                reason=str(e),
            )

        # Build onion for downstream
        downstream_onion = b""
        if len(remaining_hops) > 1:
            downstream_onion = msgpack.packb(remaining_hops[1:], use_bin_type=True)
        elif "preimage" in next_hop:
            # Last forwarding hop — pass preimage to the final destination
            downstream_onion = msgpack.packb([{"preimage": next_hop["preimage"]}], use_bin_type=True)

        # Create outgoing HTLC
        outgoing_msg = HtlcPropose(
            channel_id=next_channel.channel_id,
            payment_hash=msg.payment_hash,
            amount=msg.amount,
            timeout=next_hop.get("timeout", msg.timeout - 120),
            onion_next=downstream_onion,
        )

        outgoing_htlc = PendingHtlc(
            htlc_id=outgoing_msg.htlc_id,
            channel_id=next_channel.channel_id,
            payment_hash=msg.payment_hash,
            amount=msg.amount,
            timeout=outgoing_msg.timeout,
            upstream_htlc_id=msg.htlc_id,
            upstream_channel_id=msg.channel_id,
        )
        self.htlc_manager.add_htlc(outgoing_htlc)

        # Forward to next hop (lock serializes stream I/O per peer)
        lock = self._get_stream_lock(next_peer_id)
        try:
            async with lock:
                stream = await self._get_or_open_stream(next_peer_id)
                await write_message(stream, to_wire(MessageType.HTLC_PROPOSE, outgoing_msg))

                # Wait for response from downstream
                raw = await read_message(stream)
            resp_type, resp = from_wire(raw)

            if resp_type == MessageType.HTLC_FULFILL:
                # Downstream fulfilled — propagate preimage back upstream
                if verify_preimage(resp.preimage, msg.payment_hash):
                    self.htlc_manager.fulfill(outgoing_htlc.htlc_id, resp.preimage)
                    self.htlc_manager.fulfill(incoming.htlc_id, resp.preimage)
                    next_channel.unlock_htlc(msg.amount)
                    logger.info("htlc_forwarded_fulfilled", payment_hash=msg.payment_hash.hex()[:16])
                    return MessageType.HTLC_FULFILL, HtlcFulfill(
                        channel_id=msg.channel_id,
                        htlc_id=msg.htlc_id,
                        preimage=resp.preimage,
                    )
                else:
                    next_channel.unlock_htlc(msg.amount)
                    self.htlc_manager.cancel(outgoing_htlc.htlc_id, "Invalid preimage from downstream")
                    self.htlc_manager.cancel(incoming.htlc_id, "Invalid preimage from downstream")
                    return MessageType.HTLC_CANCEL, HtlcCancel(
                        channel_id=msg.channel_id,
                        htlc_id=msg.htlc_id,
                        reason="Invalid preimage from downstream",
                    )

            elif resp_type == MessageType.HTLC_CANCEL:
                next_channel.unlock_htlc(msg.amount)
                reason = resp.reason if hasattr(resp, "reason") else "Downstream cancelled"
                self.htlc_manager.cancel(outgoing_htlc.htlc_id, reason)
                self.htlc_manager.cancel(incoming.htlc_id, reason)
                return MessageType.HTLC_CANCEL, HtlcCancel(
                    channel_id=msg.channel_id,
                    htlc_id=msg.htlc_id,
                    reason=reason,
                )

            else:
                next_channel.unlock_htlc(msg.amount)
                self.htlc_manager.cancel(outgoing_htlc.htlc_id, "Unexpected downstream response")
                self.htlc_manager.cancel(incoming.htlc_id, "Unexpected downstream response")
                return MessageType.HTLC_CANCEL, HtlcCancel(
                    channel_id=msg.channel_id,
                    htlc_id=msg.htlc_id,
                    reason="Unexpected downstream response",
                )

        except Exception as e:
            next_channel.unlock_htlc(msg.amount)
            self.htlc_manager.cancel(outgoing_htlc.htlc_id, str(e))
            self.htlc_manager.cancel(incoming.htlc_id, str(e))
            logger.exception("htlc_forward_error")
            return MessageType.HTLC_CANCEL, HtlcCancel(
                channel_id=msg.channel_id,
                htlc_id=msg.htlc_id,
                reason=f"Forwarding error: {e}",
            )

    async def _on_htlc_fulfill(
        self, msg: Any, remote_peer: str
    ) -> tuple[MessageType, Any] | None:
        """Handle HTLC fulfill from downstream — propagate preimage upstream."""
        # This is handled inline in _on_htlc_propose for forwarding.
        # Direct fulfills arrive as responses, not unsolicited messages.
        return None

    async def _on_htlc_cancel(
        self, msg: Any, remote_peer: str
    ) -> tuple[MessageType, Any] | None:
        """Handle HTLC cancel from downstream — propagate upstream."""
        return None
