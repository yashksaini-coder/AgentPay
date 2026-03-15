"""Application configuration via pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class NodeConfig(BaseSettings):
    """libp2p node configuration."""

    model_config = SettingsConfigDict(env_prefix="NODE_")

    port: int = Field(default=9000, ge=1, le=65535, description="TCP listen port")
    ws_port: int = Field(
        default=9001, ge=0, le=65535, description="WebSocket listen port (0 to disable)"
    )
    identity_path: Path = Field(
        default=Path("~/.agentic-payments/identity.key"),
        description="Path to node identity key file",
    )
    enable_mdns: bool = Field(default=True, description="Enable mDNS peer discovery")
    enable_dht: bool = Field(default=True, description="Enable Kademlia DHT")
    bootstrap_peers: list[str] = Field(
        default_factory=list,
        description="List of bootstrap peer multiaddrs for initial network entry "
        "(e.g. /ip4/1.2.3.4/tcp/9000/p2p/QmPeer...)",
    )


class ChannelConfig(BaseSettings):
    """Payment channel protocol configuration."""

    model_config = SettingsConfigDict(env_prefix="CHANNEL_")

    challenge_period: int = Field(
        default=3600,
        ge=60,
        description="Challenge period in seconds for on-chain settlement (min 60s)",
    )
    auto_settle: bool = Field(
        default=False,
        description="Automatically settle channels on-chain after cooperative close",
    )
    max_pending_htlcs: int = Field(
        default=50,
        ge=1,
        description="Maximum concurrent pending HTLCs per channel",
    )
    htlc_timeout_base: int = Field(
        default=600,
        ge=120,
        description="Base HTLC timeout in seconds for multi-hop payments",
    )


class EthereumConfig(BaseSettings):
    """Ethereum / web3 configuration."""

    model_config = SettingsConfigDict(env_prefix="ETH_")

    rpc_url: str = Field(default="http://localhost:8545", description="Ethereum JSON-RPC URL")
    chain_id: int = Field(default=31337, ge=1, description="Chain ID (31337 = Anvil)")
    keystore_path: Path = Field(
        default=Path("~/.agentic-payments/keystore"),
        description="Ethereum keystore directory",
    )
    payment_channel_address: str = Field(
        default="", description="Deployed PaymentChannel contract address"
    )
    token_address: str = Field(
        default="",
        description="ERC-20 token address for token-based channels (empty = ETH)",
    )


class DatabaseConfig(BaseSettings):
    """PostgreSQL configuration."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    url: str = Field(
        default="postgresql://agent:agent@localhost:5432/agentic_payments",
        description="Database connection URL",
    )


class APIConfig(BaseSettings):
    """REST/WebSocket API configuration."""

    model_config = SettingsConfigDict(env_prefix="API_")

    host: str = Field(default="127.0.0.1", description="API listen address")
    port: int = Field(default=8080, ge=1, le=65535, description="API listen port")


class DiscoveryConfig(BaseSettings):
    """Agent discovery configuration."""

    model_config = SettingsConfigDict(env_prefix="DISCOVERY_")

    capabilities: list[dict] = Field(
        default_factory=list,
        description="List of capabilities: [{service_type, price_per_call, description}]",
    )
    advertisement_interval: int = Field(
        default=60,
        ge=10,
        description="How often to re-broadcast capabilities (seconds)",
    )
    stale_threshold: int = Field(
        default=300,
        ge=30,
        description="Remove agents not seen for this many seconds",
    )


class PolicyConfig(BaseSettings):
    """Wallet policy configuration."""

    model_config = SettingsConfigDict(env_prefix="POLICY_")

    max_spend_per_tx: int = Field(
        default=0, ge=0, description="Max wei per transaction (0=unlimited)"
    )
    max_total_spend: int = Field(default=0, ge=0, description="Max total wei spend (0=unlimited)")
    rate_limit_per_min: int = Field(
        default=0, ge=0, description="Max payments per minute (0=unlimited)"
    )
    peer_whitelist: list[str] = Field(default_factory=list, description="Allowed peer IDs")
    peer_blacklist: list[str] = Field(default_factory=list, description="Blocked peer IDs")


class GatewayConfig(BaseSettings):
    """x402 Resource Gateway configuration."""

    model_config = SettingsConfigDict(env_prefix="GATEWAY_")

    resources: list[dict] = Field(
        default_factory=list,
        description="List of gated resources: [{path, price, description, payment_type}]",
    )


class AlgorandConfig(BaseSettings):
    """Algorand / algosdk configuration for cross-chain settlement."""

    model_config = SettingsConfigDict(env_prefix="ALGO_")

    algod_url: str = Field(default="http://localhost:4001", description="Algorand node URL")
    algod_token: str = Field(
        default="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        description="Algorand node API token",
    )
    indexer_url: str = Field(default="", description="Algorand indexer URL (optional)")
    indexer_token: str = Field(default="", description="Algorand indexer API token")
    app_id: int = Field(default=0, ge=0, description="Deployed payment channel application ID")
    network: Literal["testnet", "mainnet", "localnet"] = Field(
        default="localnet", description="Algorand network"
    )
    keystore_path: Path = Field(
        default=Path("~/.agentic-payments/algorand_key"),
        description="Algorand key file path",
    )


class FilecoinConfig(BaseSettings):
    """Filecoin / FEVM configuration."""

    model_config = SettingsConfigDict(env_prefix="FIL_")

    rpc_url: str = Field(
        default="https://api.calibration.node.glif.io/rpc/v1",
        description="Filecoin Lotus JSON-RPC URL",
    )
    chain_id: int = Field(default=314159, ge=1, description="Chain ID (314=Mainnet, 314159=Calibration)")
    keystore_path: Path = Field(
        default=Path("~/.agentic-payments/filecoin_keystore"),
        description="Filecoin keystore file path",
    )
    payment_channel_address: str = Field(
        default="", description="PaymentChannel contract address on FEVM"
    )
    network: Literal["mainnet", "calibration", "localnet"] = Field(
        default="calibration", description="Filecoin network"
    )


class ERC8004Config(BaseSettings):
    """ERC-8004 agent identity standard configuration."""

    model_config = SettingsConfigDict(env_prefix="ERC8004_")

    enabled: bool = Field(default=False, description="Enable ERC-8004 on-chain agent identity")
    identity_registry_address: str = Field(
        default="", description="ERC-8004 Identity Registry contract address"
    )
    reputation_registry_address: str = Field(
        default="", description="ERC-8004 Reputation Registry contract address"
    )
    rpc_url: str = Field(
        default="", description="RPC URL for ERC-8004 chain (empty = use ethereum.rpc_url)"
    )
    auto_register: bool = Field(
        default=False, description="Automatically register on-chain at startup"
    )
    auto_sync_reputation: bool = Field(
        default=False, description="Automatically push trust scores to on-chain registry"
    )


class StorageConfig(BaseSettings):
    """IPFS content-addressed storage configuration."""

    model_config = SettingsConfigDict(env_prefix="STORAGE_")

    ipfs_api_url: str = Field(
        default="http://localhost:5001", description="IPFS HTTP API URL"
    )
    auto_pin_receipts: bool = Field(
        default=False, description="Automatically pin receipts to IPFS on creation"
    )
    auto_pin_capabilities: bool = Field(
        default=False, description="Automatically pin capability advertisements to IPFS"
    )
    enabled: bool = Field(default=False, description="Enable IPFS storage integration")


class PricingConfig(BaseSettings):
    """Dynamic pricing configuration."""

    model_config = SettingsConfigDict(env_prefix="PRICING_")

    trust_discount_factor: float = Field(
        default=0.3, ge=0, le=1.0, description="Max trust discount (30%)"
    )
    congestion_premium_factor: float = Field(
        default=0.5, ge=0, le=2.0, description="Max congestion premium (50%)"
    )
    min_price: int = Field(default=0, ge=0, description="Price floor in wei")
    max_price: int = Field(default=0, ge=0, description="Price ceiling in wei (0=unlimited)")
    congestion_threshold: int = Field(
        default=20, ge=1, description="Active channels at full congestion"
    )


class DisputeConfig(BaseSettings):
    """Dispute resolution configuration."""

    model_config = SettingsConfigDict(env_prefix="DISPUTE_")

    auto_challenge: bool = Field(
        default=True, description="Auto-file challenges for stale vouchers"
    )
    scan_interval: int = Field(default=30, ge=5, description="Channel scan interval in seconds")
    slash_percentage: float = Field(
        default=0.10, ge=0, le=1.0, description="Slash percentage of deposit"
    )


class Settings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(env_prefix="AGENTPAY_")

    node: NodeConfig = Field(default_factory=NodeConfig)
    channel: ChannelConfig = Field(default_factory=ChannelConfig)
    ethereum: EthereumConfig = Field(default_factory=EthereumConfig)
    algorand: AlgorandConfig = Field(default_factory=AlgorandConfig)
    filecoin: FilecoinConfig = Field(default_factory=FilecoinConfig)
    erc8004: ERC8004Config = Field(default_factory=ERC8004Config)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    pricing: PricingConfig = Field(default_factory=PricingConfig)
    dispute: DisputeConfig = Field(default_factory=DisputeConfig)
    chain_type: Literal["ethereum", "algorand", "filecoin"] = Field(
        default="ethereum", description="Primary chain for settlement"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Log level"
    )
    log_format: Literal["console", "json"] = Field(
        default="console", description="Log format: console or json"
    )
