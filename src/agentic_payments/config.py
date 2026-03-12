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
        default=3600, ge=60,
        description="Challenge period in seconds for on-chain settlement (min 60s)",
    )
    auto_settle: bool = Field(
        default=False,
        description="Automatically settle channels on-chain after cooperative close",
    )
    max_pending_htlcs: int = Field(
        default=50, ge=1,
        description="Maximum concurrent pending HTLCs per channel",
    )
    htlc_timeout_base: int = Field(
        default=600, ge=120,
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
        default="", description="ERC-20 token address for token-based channels (empty = ETH)",
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


class Settings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(env_prefix="AGENTPAY_")

    node: NodeConfig = Field(default_factory=NodeConfig)
    channel: ChannelConfig = Field(default_factory=ChannelConfig)
    ethereum: EthereumConfig = Field(default_factory=EthereumConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Log level"
    )
    log_format: Literal["console", "json"] = Field(
        default="console", description="Log format: console or json"
    )
