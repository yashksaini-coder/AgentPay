"""AgentNode: central orchestrator for a payment-capable libp2p agent."""

from __future__ import annotations

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
    MessageType,
    PaymentClose,
    PaymentOpen,
    from_wire,
    to_wire,
)
from agentic_payments.pubsub.broadcaster import PubsubBroadcaster
from agentic_payments.pubsub.topics import TOPIC_AGENT_DISCOVERY

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
        self.listen_addrs: list[str] = []
        self._nursery: trio.Nursery | None = None
        self._streams: dict[str, NetStream] = {}

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
        self.protocol_handler = PaymentProtocolHandler(self.channel_manager)

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

            # --- Peer discovery ---
            self.discovery = PeerDiscovery(self.host)
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

        try:
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

        return channel

    async def pay(self, channel_id: bytes, amount: int) -> SignedVoucher:
        """Send a micropayment voucher on an existing channel.

        Creates a signed voucher, sends it, waits for ACK.
        Evicts stale streams on error and retries once.
        """
        self._require_started()
        channel = self.channel_manager.get_channel(channel_id)
        peer_id = channel.peer_id

        async def _attempt_pay() -> SignedVoucher:
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
            _, ack = from_wire(raw)
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

        stream = await self._get_or_open_stream(peer_id)

        await write_message(stream, to_wire(MessageType.PAYMENT_CLOSE, msg))
        raw = await read_message(stream)
        _, ack = from_wire(raw)

        if ack.status == "accepted":
            channel.request_close()
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
