"""Identity bridge: maps libp2p PeerID + ETH wallet to ERC-8004 agentId.

Handles automatic registration on first startup and reputation
synchronization from the local ReputationTracker to the on-chain
ERC-8004 Reputation Registry.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from agentic_payments.identity.erc8004 import ERC8004Client
from agentic_payments.identity.models import AgentIdentity, AgentRegistrationFile

logger = structlog.get_logger(__name__)


class IdentityBridge:
    """Maps libp2p identity + ETH wallet to ERC-8004 on-chain identity.

    Provides:
    - Automatic agent registration if not already on-chain
    - Off-chain registration file generation (for agentURI)
    - Reputation sync from local trust_score to on-chain registry
    """

    def __init__(
        self,
        client: ERC8004Client,
        peer_id: str,
        wallet_address: str,
    ) -> None:
        self.client = client
        self.peer_id = peer_id
        self.wallet_address = wallet_address
        self._identity: AgentIdentity | None = None
        self._last_reputation_push: float = 0.0

    @property
    def identity(self) -> AgentIdentity | None:
        """Current on-chain identity, or None if not registered."""
        return self._identity

    @property
    def agent_id(self) -> int | None:
        """ERC-8004 agent token ID, or None if not registered."""
        return self._identity.agent_id if self._identity else None

    async def ensure_registered(self, wallet: Any, agent_uri: str = "") -> AgentIdentity:
        """Register on-chain if not already. Returns identity.

        If the agent is already registered (address has a token),
        loads the existing identity. Otherwise mints a new token.
        """
        # Check if already registered
        existing = await self.client.lookup_by_address(self.wallet_address)
        if existing:
            existing.peer_id = self.peer_id
            self._identity = existing
            logger.info(
                "erc8004_identity_loaded",
                agent_id=existing.agent_id,
                address=self.wallet_address,
            )
            return existing

        # Generate URI if not provided
        if not agent_uri:
            agent_uri = f"agentpay://{self.peer_id}"

        # Register new
        agent_id, tx_hash = await self.client.register_agent(wallet, agent_uri)
        identity = AgentIdentity(
            agent_id=agent_id,
            eth_address=self.wallet_address,
            peer_id=self.peer_id,
            agent_uri=agent_uri,
            registered_on_chain=True,
            chain_id=self.client.w3.eth.chain_id,
            registration_tx=tx_hash,
        )
        self._identity = identity
        logger.info(
            "erc8004_identity_registered",
            agent_id=agent_id,
            peer_id=self.peer_id,
            tx_hash=tx_hash,
        )
        return identity

    def build_registration_file(
        self,
        capabilities: list[dict],
        addrs: list[str],
        name: str = "AgentPay Node",
    ) -> dict:
        """Build the off-chain registration file content for agentURI.

        This JSON file is what other agents resolve when they look up
        an agentURI from the Identity Registry.
        """
        reg_file = AgentRegistrationFile(
            name=name,
            peer_id=self.peer_id,
            eth_address=self.wallet_address,
            capabilities=capabilities,
            endpoints=addrs,
        )
        return reg_file.to_dict()

    async def sync_reputation(
        self,
        trust_score: float,
        wallet: Any,
        tag: str = "payment",
        min_interval: float = 60.0,
    ) -> str | None:
        """Push local trust_score to ERC-8004 Reputation Registry.

        Rate-limited to avoid excessive on-chain transactions.
        Returns tx_hash if pushed, None if skipped.
        """
        if not self._identity or self._identity.agent_id is None:
            return None

        now = time.time()
        if now - self._last_reputation_push < min_interval:
            return None

        tx_hash = await self.client.push_reputation(
            self._identity.agent_id, trust_score, tag, wallet
        )
        self._last_reputation_push = now
        return tx_hash
