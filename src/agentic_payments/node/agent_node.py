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
from libp2p.pubsub.score import ScoreParams, TopicScoreParams
from multiaddr import Multiaddr

from agentic_payments.chain.protocols import WalletProtocol, SettlementProtocol
from agentic_payments.chain.wallet import Wallet
from agentic_payments.config import Settings
from agentic_payments.disputes.monitor import DisputeMonitor
from agentic_payments.pricing.engine import PricingEngine, PricingPolicy
from agentic_payments.sla.monitor import SLAMonitor
from agentic_payments.discovery.models import AgentAdvertisement, AgentCapability
from agentic_payments.discovery.registry import CapabilityRegistry
from agentic_payments.gateway.x402 import GatedResource, X402Gateway
from agentic_payments.identity.eip191 import IdentityProof, sign_identity, verify_identity
from agentic_payments.negotiation.manager import NegotiationManager
from agentic_payments.node.discovery import PeerDiscovery
from agentic_payments.agent.coordinator import CoordinatorBehavior
from agentic_payments.agent.executor import EchoExecutor
from agentic_payments.agent.negotiator import AutonomousNegotiator, NegotiationConfig
from agentic_payments.agent.runtime import AgentRuntime
from agentic_payments.agent.worker import WorkerBehavior
from agentic_payments.node.roles import AgentRole, RoleManager
from agentic_payments.node.identity import load_or_generate_identity, peer_id_from_keypair
from agentic_payments.payments.channel import PaymentChannel
from agentic_payments.payments.manager import ChannelManager
from agentic_payments.payments.voucher import SignedVoucher
from agentic_payments.policies.engine import PolicyEngine, WalletPolicy
from agentic_payments.protocol.codec import read_message, write_message
from agentic_payments.protocol.handler import PROTOCOL_ID, PaymentProtocolHandler
from agentic_payments.protocol.messages import (
    HtlcPropose,
    MessageType,
    PaymentAck,
    PaymentClose,
    PaymentOpen,
    from_wire,
    to_wire,
)
from agentic_payments.pubsub.broadcaster import PubsubBroadcaster
from agentic_payments.pubsub.topics import (
    TOPIC_AGENT_CAPABILITIES,
    TOPIC_AGENT_DISCOVERY,
    TOPIC_CHANNEL_ANNOUNCEMENTS,
    TOPIC_PAYMENT_RECEIPTS,
)
from agentic_payments.reporting.receipts import ReceiptStore, SignedReceipt
from agentic_payments.reputation.tracker import ReputationTracker
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
        self.wallet: WalletProtocol | None = None
        self.settlement: SettlementProtocol | None = None
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

        # EIP-191 identity binding
        self.identity_proof: IdentityProof | None = None
        self._verified_identities: dict[str, IdentityProof] = {}  # peer_id -> proof

        # --- New subsystems ---
        self.capability_registry: CapabilityRegistry = CapabilityRegistry(
            stale_threshold=config.discovery.stale_threshold
        )
        self.negotiation_manager: NegotiationManager = NegotiationManager()
        self.policy_engine: PolicyEngine = PolicyEngine(
            WalletPolicy(
                max_spend_per_tx=config.policy.max_spend_per_tx,
                max_total_spend=config.policy.max_total_spend,
                rate_limit_per_min=config.policy.rate_limit_per_min,
                peer_whitelist=config.policy.peer_whitelist,
                peer_blacklist=config.policy.peer_blacklist,
            )
        )
        self.reputation_tracker: ReputationTracker = ReputationTracker()
        self.receipt_store: ReceiptStore = ReceiptStore()
        self.gateway: X402Gateway = X402Gateway()
        self.sla_monitor: SLAMonitor = SLAMonitor()
        self.erc8004_client = None
        self.identity_bridge = None
        self.pricing_engine: PricingEngine | None = None  # initialized after wallet
        self.dispute_monitor: DisputeMonitor | None = None  # initialized after channel_manager
        self.role_manager: RoleManager = RoleManager()
        self.runtime: AgentRuntime | None = None

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

        # --- Wallet (chain-aware) ---
        if self.config.chain_type == "algorand":
            from agentic_payments.chain.algorand.wallet import AlgorandWallet

            keypath = self.config.algorand.keystore_path
            try:
                self.wallet = AlgorandWallet.from_keyfile(keypath)
                logger.info("algorand_wallet_loaded", address=self.wallet.address)
            except (FileNotFoundError, ValueError):
                self.wallet = AlgorandWallet.generate()
                self.wallet.save_keyfile(keypath)
                logger.info("algorand_wallet_generated", address=self.wallet.address)
        elif self.config.chain_type == "filecoin":
            from agentic_payments.chain.filecoin.wallet import FilecoinWallet

            keypath = self.config.filecoin.keystore_path
            try:
                self.wallet = FilecoinWallet.from_keyfile(keypath)
                logger.info("filecoin_wallet_loaded", address=self.wallet.address)
            except (FileNotFoundError, ValueError):
                self.wallet = FilecoinWallet.generate()
                self.wallet.save_keyfile(keypath)
                logger.info("filecoin_wallet_generated", address=self.wallet.address)
        else:
            self.wallet = Wallet.generate()
            logger.info("ethereum_wallet_generated", address=self.wallet.address)

        self.channel_manager = ChannelManager(self.wallet.address, policy_engine=self.policy_engine)

        # --- EIP-191 Identity Binding ---
        self.identity_proof = sign_identity(
            peer_id=self.peer_id.to_base58(),
            private_key=self.wallet.private_key,
        )
        logger.info(
            "eip191_identity_bound",
            peer_id=self.peer_id.to_base58()[:16],
            eth_address=self.wallet.address,
        )

        # --- Settlement (chain-aware, optional — requires RPC connectivity) ---
        if self.config.chain_type == "algorand" and self.config.algorand.app_id:
            try:
                from agentic_payments.chain.algorand.settlement import AlgorandSettlement

                self.settlement = AlgorandSettlement(
                    algod_url=self.config.algorand.algod_url,
                    algod_token=self.config.algorand.algod_token,
                    app_id=self.config.algorand.app_id,
                    wallet=self.wallet,
                    indexer_url=self.config.algorand.indexer_url,
                    indexer_token=self.config.algorand.indexer_token,
                )
                logger.info("algorand_settlement_ready", app_id=self.config.algorand.app_id)
            except Exception as e:
                logger.warning("algorand_settlement_unavailable", error=str(e))
                self.settlement = None
        elif self.config.chain_type == "filecoin" and self.config.filecoin.payment_channel_address:
            try:
                from web3 import Web3
                from agentic_payments.chain.filecoin.settlement import FilecoinSettlement

                w3 = Web3(Web3.HTTPProvider(self.config.filecoin.rpc_url))
                self.settlement = FilecoinSettlement(
                    w3=w3,
                    contract_address=self.config.filecoin.payment_channel_address,
                    wallet=self.wallet,  # type: ignore[arg-type]
                )
                logger.info("filecoin_settlement_ready", rpc=self.config.filecoin.rpc_url)
            except Exception as e:
                logger.warning("filecoin_settlement_unavailable", error=str(e))
                self.settlement = None
        elif self.config.chain_type == "ethereum" and self.config.ethereum.payment_channel_address:
            try:
                from web3 import Web3
                from agentic_payments.chain.settlement import Settlement

                w3 = Web3(Web3.HTTPProvider(self.config.ethereum.rpc_url))
                self.settlement = Settlement(
                    w3=w3,
                    contract_address=self.config.ethereum.payment_channel_address,
                    wallet=self.wallet,  # type: ignore[arg-type]
                )
                logger.info("ethereum_settlement_ready", rpc=self.config.ethereum.rpc_url)
            except Exception as e:
                logger.warning("ethereum_settlement_unavailable", error=str(e))
                self.settlement = None

        # --- IPFS Storage (optional) ---
        self.ipfs_client = None
        self.ipfs_receipt_store = None
        if self.config.storage.enabled:
            try:
                from agentic_payments.storage.ipfs import IPFSClient
                from agentic_payments.storage.receipt_store import IPFSReceiptStore

                self.ipfs_client = IPFSClient(self.config.storage.ipfs_api_url)
                self.ipfs_receipt_store = IPFSReceiptStore(self.ipfs_client, self.receipt_store)
                logger.info("ipfs_storage_ready", api=self.config.storage.ipfs_api_url)
            except Exception as e:
                logger.warning("ipfs_storage_unavailable", error=str(e))
                self.ipfs_client = None

        # --- ERC-8004 Agent Identity (optional) ---
        if self.config.erc8004.enabled and self.config.erc8004.identity_registry_address:
            try:
                from web3 import Web3 as Web3Import
                from agentic_payments.identity.erc8004 import ERC8004Client
                from agentic_payments.identity.bridge import IdentityBridge

                rpc = self.config.erc8004.rpc_url or self.config.ethereum.rpc_url
                w3 = Web3Import(Web3Import.HTTPProvider(rpc))
                self.erc8004_client = ERC8004Client(  # type: ignore[assignment]
                    w3=w3,
                    identity_addr=self.config.erc8004.identity_registry_address,
                    reputation_addr=self.config.erc8004.reputation_registry_address,
                )
                self.identity_bridge = IdentityBridge(  # type: ignore[assignment]
                    client=self.erc8004_client,  # type: ignore[arg-type]
                    peer_id=self.peer_id.to_base58() if self.peer_id else "",
                    wallet_address=self.wallet.address,
                )
                logger.info("erc8004_identity_ready")
            except Exception as e:
                logger.warning("erc8004_identity_unavailable", error=str(e))
                self.erc8004_client = None
                self.identity_bridge = None

        self.protocol_handler = PaymentProtocolHandler(
            channel_manager=self.channel_manager,
            htlc_manager=self.htlc_manager,
            on_htlc_propose=self._on_htlc_propose,
            on_htlc_fulfill=self._on_htlc_fulfill,
            on_htlc_cancel=self._on_htlc_cancel,
            on_channel_opened=self._on_channel_accepted,
            on_negotiate_propose=self._on_negotiate_propose,
            on_negotiate_counter=self._on_negotiate_counter,
            on_negotiate_accept=self._on_negotiate_accept,
            on_negotiate_reject=self._on_negotiate_reject,
        )

        # --- Pricing, Disputes, SLA ---
        self.pricing_engine = PricingEngine(
            reputation_tracker=self.reputation_tracker,
            channel_manager=self.channel_manager,
            policy=PricingPolicy(
                trust_discount_factor=self.config.pricing.trust_discount_factor,
                congestion_premium_factor=self.config.pricing.congestion_premium_factor,
                min_price=self.config.pricing.min_price,
                max_price=self.config.pricing.max_price,
                congestion_threshold=self.config.pricing.congestion_threshold,
            ),
        )
        self.dispute_monitor = DisputeMonitor(
            channel_manager=self.channel_manager,
            reputation_tracker=self.reputation_tracker,
            auto_challenge=self.config.dispute.auto_challenge,
            scan_interval=self.config.dispute.scan_interval,
            slash_percentage=self.config.dispute.slash_percentage,
        )

        # --- Configure gateway ---
        self.gateway.provider_id = self.peer_id.to_base58()
        self.gateway.wallet_address = self.wallet.address
        for r in self.config.gateway.resources:
            self.gateway.register_resource(GatedResource.from_dict(r))

        # --- libp2p host ---
        self.host = new_host(  # type: ignore[assignment]
            key_pair=key_pair,
            muxer_preference="YAMUX",
            enable_mDNS=self.config.node.enable_mdns,
        )

        # --- Register payment protocol ---
        self.host.set_stream_handler(  # type: ignore[union-attr]
            TProtocol(PROTOCOL_ID),
            self._handle_incoming_stream,  # type: ignore[arg-type]
        )

        # --- Listen addresses ---
        listen_addrs = [
            Multiaddr(f"/ip4/0.0.0.0/tcp/{self.config.node.port}"),
        ]
        if self.config.node.ws_port:
            listen_addrs.append(Multiaddr(f"/ip4/0.0.0.0/tcp/{self.config.node.ws_port}/ws"))

        # --- Start host ---
        async with self.host.run(listen_addrs=listen_addrs):  # type: ignore[union-attr]
            self.listen_addrs = [str(addr) for addr in self.host.get_addrs()]  # type: ignore[union-attr]
            logger.info(
                "agent_node_started",
                peer_id=self.peer_id.to_base58(),
                addrs=self.listen_addrs,
                chain=self.config.chain_type,
                address=self.wallet.address,
                settlement="active" if self.settlement else "off-chain only",
            )

            # --- GossipSub pubsub (with peer scoring) ---
            score_params = self._build_gossipsub_score_params()
            self.gossipsub = GossipSub(
                protocols=GOSSIPSUB_PROTOCOLS,
                degree=8,
                degree_low=6,
                degree_high=12,
                heartbeat_interval=120,
                score_params=score_params,
            )
            self.pubsub = Pubsub(
                host=self.host,  # type: ignore[arg-type]
                router=self.gossipsub,
                strict_signing=True,
            )
            self.broadcaster = PubsubBroadcaster(self.pubsub)

            # Run pubsub as an async service
            nursery.start_soon(self._run_pubsub)

            # --- Peer discovery (with bootstrap peers) ---
            self.discovery = PeerDiscovery(
                self.host,  # type: ignore[arg-type]
                bootstrap_addrs=self.config.node.bootstrap_peers,
            )
            nursery.start_soon(self.discovery.run, nursery)

            # --- REST API ---
            from agentic_payments.api.server import serve_api

            await nursery.start(serve_api, self.config.api, self)

            # --- Agent Runtime (optional) ---
            if self.config.agent.enabled:
                strategies: list = []

                # Build negotiator if enabled
                if self.config.agent.auto_negotiate:
                    strategies.append(
                        AutonomousNegotiator(
                            NegotiationConfig(
                                max_price=self.config.agent.max_price,
                                min_trust_score=self.config.agent.min_trust_score,
                            )
                        )
                    )

                # Role-specific strategies
                role = self.role_manager.role
                if role == AgentRole.WORKER:
                    strategies.append(WorkerBehavior(executor=EchoExecutor()))
                elif role == AgentRole.COORDINATOR:
                    strategies.append(CoordinatorBehavior())

                self.runtime = AgentRuntime(
                    node=self,
                    strategies=strategies,
                    executor=EchoExecutor(),
                    tick_interval=self.config.agent.tick_interval,
                )
                await nursery.start(self.runtime.run)
                logger.info(
                    "agent_runtime_launched",
                    strategies=[type(s).__name__ for s in strategies],
                    tick_interval=self.config.agent.tick_interval,
                )

            # Block until cancelled
            await trio.sleep_forever()

    def _build_gossipsub_score_params(self) -> ScoreParams:
        """Build GossipSub scoring parameters wired to our reputation system.

        Scoring weights (inspired by libp2p-v4-swap-agents):
        - P1 (time in mesh): weight 0.5, cap 3600
        - P2 (first message deliveries): weight 1.0, cap 100
        - P3 (mesh message deliveries): weight -1.0 (penalty for slow delivery)
        - P4 (invalid messages): weight -10.0 (harsh penalty)
        - P6 (app-specific): weight 10.0, uses reputation_tracker trust scores
        - Graylist threshold: -400 (matches libp2p-v4-swap-agents)
        """

        def _app_score(peer_id: PeerID) -> float:
            """Map reputation trust score (0.0-1.0) to app-specific score (-100 to +100)."""
            trust = self.reputation_tracker.get_trust_score(str(peer_id))
            # Map 0.0-1.0 → -100 to +100 (0.5 = neutral = 0)
            return (trust - 0.5) * 200

        return ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=0.5, cap=3600.0, decay=0.9997),
            p2_first_message_deliveries=TopicScoreParams(weight=1.0, cap=100.0, decay=0.999),
            p3_mesh_message_deliveries=TopicScoreParams(weight=-1.0, cap=0.0, decay=0.997),
            p4_invalid_messages=TopicScoreParams(weight=-10.0, cap=0.0, decay=0.99),
            p6_appl_slack_weight=10.0,
            p6_appl_slack_decay=0.999,
            graylist_threshold=-400.0,
            gossip_threshold=-100.0,
            publish_threshold=-200.0,
            app_specific_score_fn=_app_score,
        )

    async def _run_pubsub(self) -> None:
        """Run the GossipSub pubsub service and subscribe to all topics."""
        try:
            async with background_trio_service(self.pubsub):  # type: ignore[arg-type]
                await self.broadcaster.subscribe_all()  # type: ignore[union-attr]

                # Announce ourselves on the discovery topic (with EIP-191 proof)
                announce_data = {
                    "type": "announce",
                    "peer_id": self.peer_id.to_base58(),  # type: ignore[union-attr]
                    "eth_address": self.wallet.address,  # type: ignore[union-attr]
                    "addrs": self.listen_addrs,
                }
                if self.identity_proof:
                    announce_data["identity_proof"] = self.identity_proof.to_dict()
                await self.broadcaster.publish(TOPIC_AGENT_DISCOVERY, announce_data)  # type: ignore[union-attr]

                # Register handlers for pubsub topics
                self.broadcaster.on_message(  # type: ignore[union-attr]
                    TOPIC_CHANNEL_ANNOUNCEMENTS,
                    self._handle_channel_announce,
                )
                self.broadcaster.on_message(  # type: ignore[union-attr]
                    TOPIC_AGENT_CAPABILITIES,
                    self._handle_capability_announce,
                )
                self.broadcaster.on_message(  # type: ignore[union-attr]
                    TOPIC_AGENT_DISCOVERY,
                    self._handle_discovery_announce,
                )
                self.broadcaster.on_message(  # type: ignore[union-attr]
                    TOPIC_PAYMENT_RECEIPTS,
                    self._handle_receipt_announce,
                )

                # Publish our own capabilities
                await self._broadcast_capabilities()

                # Sync existing local channels into the routing graph
                self._sync_graph_from_channels()

                # Announce all existing active channels on gossipsub
                for ch in self.channel_manager.list_channels():  # type: ignore[union-attr]
                    if ch.state.name in ("ACTIVE", "OPEN"):
                        await self.broadcaster.broadcast_channel(  # type: ignore[union-attr]
                            {
                                "channel_id": ch.channel_id.hex(),
                                "peer_a": self.peer_id.to_base58(),  # type: ignore[union-attr]
                                "peer_b": ch.peer_id,
                                "capacity": ch.total_deposit,
                            }
                        )

                # Run listeners for incoming pubsub messages
                await self.broadcaster.run(self._nursery)  # type: ignore[union-attr, arg-type]

                # Keep the pubsub service alive until cancelled
                await trio.sleep_forever()
        except Exception:
            logger.exception("pubsub_service_error")
            raise

    async def _handle_incoming_stream(self, stream: NetStream) -> None:
        """Handle an incoming payment protocol stream from a remote peer."""
        await self.protocol_handler.handle_stream(stream)  # type: ignore[union-attr]

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
        await self.host.connect(peer_info)  # type: ignore[union-attr]

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
        await self.host.disconnect(pid)  # type: ignore[union-attr]
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
        stream = await self.host.new_stream(pid, [TProtocol(PROTOCOL_ID)])  # type: ignore[union-attr]
        return stream  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Payment channel operations
    # ------------------------------------------------------------------

    async def open_payment_channel(
        self,
        peer_id: str,
        receiver: str,
        deposit: int,
        sla_terms: Any = None,
    ) -> PaymentChannel:
        """Open a payment channel with a connected peer.

        Opens a new libp2p stream, sends a PaymentOpen, waits for ACK.
        Cleans up channel on failure.
        """
        self._require_started()
        # Policy check
        self.policy_engine.check_channel_open(deposit, peer_id)

        msg = PaymentOpen.new(
            sender=self.wallet.address,  # type: ignore[union-attr]
            receiver=receiver,
            total_deposit=deposit,
        )

        channel = self.channel_manager.create_channel(  # type: ignore[union-attr]
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
                self.channel_manager.remove_channel(msg.channel_id)  # type: ignore[union-attr]
                raise RuntimeError(f"Channel open rejected: {ack.reason}")
        except RuntimeError:
            raise
        except Exception:
            # Clean up orphaned channel on any failure
            self.channel_manager.remove_channel(msg.channel_id)  # type: ignore[union-attr]
            raise

        # Announce channel on gossipsub for routing topology
        await self._announce_channel(channel)

        # Register SLA monitoring if terms were provided
        if sla_terms is not None:
            from agentic_payments.negotiation.models import SLATerms

            if isinstance(sla_terms, dict):
                sla_terms = SLATerms(**sla_terms)
            self.sla_monitor.register_channel(channel.channel_id.hex(), sla_terms)

        return channel

    async def pay(self, channel_id: bytes, amount: int, task_id: str = "") -> SignedVoucher:
        """Send a micropayment voucher on an existing channel.

        Creates a signed voucher, sends it, waits for ACK.
        Evicts stale streams on error and retries once.
        Uses per-peer lock to prevent concurrent stream corruption.
        """
        self._require_started()
        channel = self.channel_manager.get_channel(channel_id)  # type: ignore[union-attr]
        peer_id = channel.peer_id
        lock = self._get_stream_lock(peer_id)

        async def _attempt_pay() -> SignedVoucher:
            async with lock:
                stream = await self._get_or_open_stream(peer_id)

                async def send_fn(msg):
                    await write_message(stream, to_wire(MessageType.PAYMENT_UPDATE, msg))

                voucher = await self.channel_manager.send_payment(  # type: ignore[union-attr]
                    channel_id=channel_id,
                    amount=amount,
                    private_key=self.wallet.private_key,  # type: ignore[union-attr]
                    send_fn=send_fn,
                    task_id=task_id,
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

        t0 = time.time()
        try:
            voucher = await _attempt_pay()
        except (ConnectionError, OSError):
            # Stream may be stale — evict and retry once
            self._evict_stream(peer_id)
            logger.warning("pay_stream_error_retrying", peer_id=peer_id)
            voucher = await _attempt_pay()
        except Exception:
            response_time = time.time() - t0
            self.reputation_tracker.record_payment_failed(peer_id)
            # Record SLA failure
            self.sla_monitor.record_request(
                channel_id.hex(),
                response_time * 1000,
                success=False,
            )
            raise

        # Record reputation
        response_time = time.time() - t0
        self.reputation_tracker.record_payment_sent(peer_id, amount, response_time)

        # Record SLA metrics
        self.sla_monitor.record_request(
            channel_id.hex(),
            response_time * 1000,
            success=True,
        )

        # Create receipt
        prev_hash = self.receipt_store.get_previous_hash(channel_id)
        receipt = SignedReceipt.create(
            channel_id=channel_id,
            nonce=voucher.nonce,
            amount=voucher.amount,
            sender=channel.sender,
            receiver=channel.receiver,
            previous_receipt_hash=prev_hash,
            private_key=self.wallet.private_key,  # type: ignore[union-attr]
        )
        self.receipt_store.add(receipt)

        # Broadcast receipt on gossipsub
        if self.broadcaster:
            await self.broadcaster.publish(TOPIC_PAYMENT_RECEIPTS, receipt.to_dict())

        return voucher

    async def close_channel(self, channel_id: bytes) -> None:
        """Cooperatively close a payment channel.

        Sends a PaymentClose over the stream and transitions state on ACK.
        Cleans up the stream cache after closing.
        """
        self._require_started()
        channel = self.channel_manager.get_channel(channel_id)  # type: ignore[union-attr]
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
            peer_a=self.peer_id.to_base58(),  # type: ignore[union-attr]
            peer_b=channel.peer_id,
            capacity=channel.total_deposit,
        )
        await self.broadcaster.broadcast_channel(
            {
                "channel_id": channel.channel_id.hex(),
                "peer_a": self.peer_id.to_base58(),  # type: ignore[union-attr]
                "peer_b": channel.peer_id,
                "capacity": channel.total_deposit,
            }
        )

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
            source=self.peer_id.to_base58(),  # type: ignore[union-attr]
            destination=destination,
            amount=amount,
            base_timeout=base_timeout,
            reputation_fn=self.reputation_tracker.get_trust_score,
        )

    async def route_payment(self, destination: str, amount: int) -> dict:
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
                {
                    "peer_id": h.peer_id,
                    "channel_id": h.channel_id,
                    "amount": h.amount,
                    "timeout": h.timeout,
                }
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

                    await self.channel_manager.send_payment(  # type: ignore[union-attr]
                        channel_id=channel.channel_id,
                        amount=amount,
                        private_key=self.wallet.private_key,  # type: ignore[union-attr]
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
        raise RuntimeError("Unreachable: routed payment ended without result")

    def _find_channel_to_peer(self, peer_id: str) -> PaymentChannel | None:
        """Find an active channel to a specific peer where we are the sender."""
        local_addr = self.wallet.address if self.wallet else ""
        # Prefer channels where we are the sender (can pay out)
        for ch in self.channel_manager.list_channels():  # type: ignore[union-attr]
            if ch.peer_id == peer_id and ch.state.name == "ACTIVE" and ch.sender == local_addr:
                return ch
        return None

    # ------------------------------------------------------------------
    # HTLC callbacks (called by protocol handler)
    # ------------------------------------------------------------------

    async def _on_htlc_propose(self, msg: Any, remote_peer: str) -> tuple[MessageType, Any]:
        """Handle incoming HTLC proposal — either forward or settle as final hop."""
        from agentic_payments.protocol.messages import HtlcCancel, HtlcFulfill, HtlcPropose
        from agentic_payments.routing.pathfinder import TIMEOUT_DELTA

        # Validate timeout: must be in the future with enough margin
        now = int(time.time())
        if msg.timeout <= now:
            logger.warning(
                "htlc_expired_on_arrival", htlc_id=msg.htlc_id.hex()[:16], timeout=msg.timeout
            )
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
                if (
                    raw_pre
                    and isinstance(raw_pre, bytes)
                    and verify_preimage(raw_pre, msg.payment_hash)
                ):
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
            downstream_onion = msgpack.packb(
                [{"preimage": next_hop["preimage"]}], use_bin_type=True
            )

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
                    logger.info(
                        "htlc_forwarded_fulfilled", payment_hash=msg.payment_hash.hex()[:16]
                    )
                    return MessageType.HTLC_FULFILL, HtlcFulfill(
                        channel_id=msg.channel_id,
                        htlc_id=msg.htlc_id,
                        preimage=resp.preimage,
                    )
                else:
                    next_channel.unlock_htlc(msg.amount)
                    self.htlc_manager.cancel(
                        outgoing_htlc.htlc_id, "Invalid preimage from downstream"
                    )
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

    async def _on_htlc_fulfill(self, msg: Any, remote_peer: str) -> tuple[MessageType, Any] | None:
        """Handle HTLC fulfill from downstream — propagate preimage upstream."""
        self.reputation_tracker.record_htlc_fulfilled(remote_peer)
        return None

    async def _on_htlc_cancel(self, msg: Any, remote_peer: str) -> tuple[MessageType, Any] | None:
        """Handle HTLC cancel from downstream — propagate upstream."""
        self.reputation_tracker.record_htlc_cancelled(remote_peer)
        return None

    # ------------------------------------------------------------------
    # Discovery & Capability broadcasting
    # ------------------------------------------------------------------

    async def _broadcast_capabilities(self) -> None:
        """Publish our capabilities on the capability topic."""
        if not self.broadcaster:
            return
        caps = [AgentCapability.from_dict(c) for c in self.config.discovery.capabilities]
        # Wire current role into capabilities for discovery
        current_role = self.role_manager.role
        if current_role:
            for cap in caps:
                cap.role = current_role.value
        ad = AgentAdvertisement(
            peer_id=self.peer_id.to_base58(),  # type: ignore[union-attr]
            eth_address=self.wallet.address,  # type: ignore[union-attr]
            capabilities=caps,
            addrs=self.listen_addrs,
        )
        # Register ourselves in local registry
        self.capability_registry.register(ad)
        await self.broadcaster.publish(TOPIC_AGENT_CAPABILITIES, ad.to_dict())

    async def _handle_capability_announce(self, data: dict, from_peer: PeerID) -> None:
        """Handle incoming capability advertisement from gossipsub."""
        info = data.get("data", data)
        try:
            ad = AgentAdvertisement.from_dict(info)
            self.capability_registry.register(ad)
        except (KeyError, TypeError):
            logger.debug("invalid_capability_announce", from_peer=str(from_peer))

    async def _handle_discovery_announce(self, data: dict, from_peer: PeerID) -> None:
        """Handle agent discovery announcement from gossipsub.

        Registers the announcing agent into the capability registry so it can
        be found via the discovery API even before it publishes capabilities.
        """
        peer_id = data.get("peer_id", str(from_peer))
        eth_address = data.get("eth_address", "")
        addrs = data.get("addrs", [])
        if peer_id and peer_id != self.peer_id.to_base58():  # type: ignore[union-attr]
            # Verify EIP-191 identity proof if present
            proof_data = data.get("identity_proof")
            if proof_data:
                try:
                    proof = IdentityProof.from_dict(proof_data)
                    if verify_identity(proof) and proof.peer_id == peer_id:
                        self._verified_identities[peer_id] = proof
                        logger.info(
                            "eip191_identity_verified",
                            peer_id=peer_id[:16],
                            eth_address=proof.eth_address,
                        )
                    else:
                        logger.warning(
                            "eip191_identity_rejected",
                            peer_id=peer_id[:16],
                            claimed_address=proof_data.get("eth_address", ""),
                        )
                except (KeyError, ValueError, TypeError):
                    logger.debug("eip191_proof_parse_error", peer_id=peer_id[:16])

            ad = AgentAdvertisement(
                peer_id=peer_id,
                eth_address=eth_address,
                capabilities=[],
                addrs=addrs,
            )
            self.capability_registry.register(ad)
            logger.debug("discovery_peer_registered", peer_id=peer_id[:16])

    async def _handle_receipt_announce(self, data: dict, from_peer: PeerID) -> None:
        """Handle payment receipt from gossipsub.

        Stores receipts from other agents for auditability and cross-verification.
        """
        receipt_data = data.get("data", data)
        try:
            receipt = SignedReceipt.from_dict(receipt_data)
            self.receipt_store.add(receipt)
            logger.debug(
                "receipt_from_pubsub",
                from_peer=str(from_peer)[:16],
                channel=receipt.channel_id.hex()[:12],
            )
        except (KeyError, TypeError, ValueError):
            logger.debug("invalid_receipt_announce", from_peer=str(from_peer))

    # ------------------------------------------------------------------
    # Negotiation callbacks (called by protocol handler)
    # ------------------------------------------------------------------

    async def _on_negotiate_propose(
        self, msg: Any, remote_peer: str
    ) -> tuple[MessageType, Any] | None:
        """Handle incoming negotiation proposal."""
        neg = self.negotiation_manager.propose(
            initiator=remote_peer,
            responder=self.peer_id.to_base58(),  # type: ignore[union-attr]
            service_type=msg.service_type,
            proposed_price=msg.proposed_price,
            channel_deposit=msg.channel_deposit,
            timeout=float(msg.timeout),
        )
        return MessageType.PAYMENT_ACK, PaymentAck(
            channel_id=b"\x00" * 32,
            nonce=0,
            status="accepted",
            reason=neg.negotiation_id,
        )

    async def _on_negotiate_counter(
        self, msg: Any, remote_peer: str
    ) -> tuple[MessageType, Any] | None:
        """Handle incoming counter-offer."""
        from agentic_payments.protocol.messages import PaymentAck

        try:
            self.negotiation_manager.counter(msg.negotiation_id, remote_peer, msg.counter_price)
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=b"\x00" * 32, nonce=0, status="accepted"
            )
        except (KeyError, ValueError) as e:
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=b"\x00" * 32, nonce=0, status="rejected", reason=str(e)
            )

    async def _on_negotiate_accept(
        self, msg: Any, remote_peer: str
    ) -> tuple[MessageType, Any] | None:
        """Handle negotiation acceptance."""
        from agentic_payments.protocol.messages import PaymentAck

        try:
            self.negotiation_manager.accept(msg.negotiation_id, remote_peer)
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=b"\x00" * 32, nonce=0, status="accepted"
            )
        except (KeyError, ValueError) as e:
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=b"\x00" * 32, nonce=0, status="rejected", reason=str(e)
            )

    async def _on_negotiate_reject(
        self, msg: Any, remote_peer: str
    ) -> tuple[MessageType, Any] | None:
        """Handle negotiation rejection."""
        from agentic_payments.protocol.messages import PaymentAck

        try:
            self.negotiation_manager.reject(msg.negotiation_id, remote_peer)
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=b"\x00" * 32, nonce=0, status="accepted"
            )
        except (KeyError, ValueError) as e:
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=b"\x00" * 32, nonce=0, status="rejected", reason=str(e)
            )

    async def negotiate(
        self,
        peer_id: str,
        service_type: str,
        proposed_price: int,
        channel_deposit: int,
        sla_terms: Any = None,
    ) -> dict:
        """Initiate a negotiation with a peer. Auto-opens channel on accept."""
        self._require_started()
        neg = self.negotiation_manager.propose(
            initiator=self.peer_id.to_base58(),  # type: ignore[union-attr]
            responder=peer_id,
            service_type=service_type,
            proposed_price=proposed_price,
            channel_deposit=channel_deposit,
            sla_terms=sla_terms,
        )
        return neg.to_dict()
