"""ERC-8004 on-chain agent identity and reputation client.

Interacts with the ERC-8004 Identity Registry (ERC-721) and Reputation
Registry via web3.py. Compatible with Ethereum mainnet, testnets, and
local Anvil deployments with mock contracts.

References:
- EIP-8004: https://eips.ethereum.org/EIPS/eip-8004
- Agent0 SDK: https://docs.sdk.ag0.xyz/
"""

from __future__ import annotations

from typing import Any

import structlog
import trio
from web3 import Web3
from web3.contract import Contract

from agentic_payments.identity.models import AgentIdentity

logger = structlog.get_logger(__name__)

# ── ERC-8004 Identity Registry ABI (ERC-721 + agent registration) ──

ERC8004_IDENTITY_ABI: list[dict[str, Any]] = [
    {
        "inputs": [{"name": "uri", "type": "string"}],
        "name": "registerAgent",
        "outputs": [{"name": "agentId", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "name": "agentURI",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "agentIdOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    # Event: AgentRegistered(uint256 indexed agentId, address indexed owner, string uri)
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "agentId", "type": "uint256"},
            {"indexed": True, "name": "owner", "type": "address"},
            {"indexed": False, "name": "uri", "type": "string"},
        ],
        "name": "AgentRegistered",
        "type": "event",
    },
]

# ── ERC-8004 Reputation Registry ABI ──

ERC8004_REPUTATION_ABI: list[dict[str, Any]] = [
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "score", "type": "uint8"},
            {"name": "tag", "type": "string"},
        ],
        "name": "submitFeedback",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "agentId", "type": "uint256"}],
        "name": "getReputationSummary",
        "outputs": [
            {"name": "avgScore", "type": "uint8"},
            {"name": "feedbackCount", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "agentId", "type": "uint256"},
            {"indexed": True, "name": "reviewer", "type": "address"},
            {"indexed": False, "name": "score", "type": "uint8"},
            {"indexed": False, "name": "tag", "type": "string"},
        ],
        "name": "FeedbackSubmitted",
        "type": "event",
    },
]


def _get_identity_contract(w3: Web3, address: str) -> Contract:
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=ERC8004_IDENTITY_ABI)


def _get_reputation_contract(w3: Web3, address: str) -> Contract:
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=ERC8004_REPUTATION_ABI)


class ERC8004Client:
    """Client for ERC-8004 Identity and Reputation Registries.

    All on-chain calls are executed in trio worker threads to avoid
    blocking the event loop.
    """

    def __init__(self, w3: Web3, identity_addr: str, reputation_addr: str) -> None:
        self.w3 = w3
        self.identity = _get_identity_contract(w3, identity_addr)
        self.reputation = _get_reputation_contract(w3, reputation_addr)

    async def register_agent(
        self, wallet: Any, agent_uri: str
    ) -> tuple[int, str]:
        """Register an agent on-chain. Returns (agentId, tx_hash).

        Mints an ERC-721 identity token with the given agentURI.
        """

        def _register() -> tuple[int, str]:
            nonce = self.w3.eth.get_transaction_count(wallet.address)
            tx = self.identity.functions.registerAgent(agent_uri).build_transaction(
                {"from": wallet.address, "nonce": nonce}
            )
            signed = wallet.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)

            # Parse AgentRegistered event
            logs = self.identity.events.AgentRegistered().process_receipt(receipt)
            agent_id = logs[0]["args"]["agentId"] if logs else 0

            return agent_id, tx_hash.hex()

        agent_id, tx_hash = await trio.to_thread.run_sync(_register)
        logger.info(
            "erc8004_agent_registered",
            agent_id=agent_id,
            tx_hash=tx_hash,
            uri=agent_uri[:60],
        )
        return agent_id, tx_hash

    async def lookup_agent(self, agent_id: int) -> AgentIdentity | None:
        """Look up an agent by ERC-8004 token ID."""

        def _lookup() -> AgentIdentity | None:
            try:
                uri = self.identity.functions.agentURI(agent_id).call()
                owner = self.identity.functions.ownerOf(agent_id).call()
                return AgentIdentity(
                    agent_id=agent_id,
                    eth_address=owner,
                    peer_id="",  # Resolved from off-chain registration file
                    agent_uri=uri,
                    registered_on_chain=True,
                    chain_id=self.w3.eth.chain_id,
                )
            except Exception:
                return None

        return await trio.to_thread.run_sync(_lookup)

    async def lookup_by_address(self, address: str) -> AgentIdentity | None:
        """Look up an agent by ETH address."""

        def _lookup() -> AgentIdentity | None:
            try:
                address_cs = Web3.to_checksum_address(address)
                agent_id = self.identity.functions.agentIdOf(address_cs).call()
                if agent_id == 0:
                    return None
                uri = self.identity.functions.agentURI(agent_id).call()
                return AgentIdentity(
                    agent_id=agent_id,
                    eth_address=address_cs,
                    peer_id="",
                    agent_uri=uri,
                    registered_on_chain=True,
                    chain_id=self.w3.eth.chain_id,
                )
            except Exception:
                return None

        return await trio.to_thread.run_sync(_lookup)

    async def push_reputation(
        self, agent_id: int, score_float: float, tag: str, wallet: Any
    ) -> str:
        """Push a trust score to the ERC-8004 Reputation Registry.

        Converts our 0.0-1.0 float to ERC-8004's 0-100 uint8.
        Returns tx_hash.
        """
        score_uint8 = trust_score_to_erc8004(score_float)

        def _push() -> str:
            nonce = self.w3.eth.get_transaction_count(wallet.address)
            tx = self.reputation.functions.submitFeedback(
                agent_id, score_uint8, tag
            ).build_transaction({"from": wallet.address, "nonce": nonce})
            signed = wallet.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed)
            self.w3.eth.wait_for_transaction_receipt(tx_hash)
            return tx_hash.hex()

        tx_hash = await trio.to_thread.run_sync(_push)
        logger.info(
            "erc8004_reputation_pushed",
            agent_id=agent_id,
            score=score_uint8,
            tag=tag,
            tx_hash=tx_hash,
        )
        return tx_hash

    async def get_reputation(self, agent_id: int) -> dict:
        """Fetch on-chain reputation summary."""

        def _get() -> dict:
            try:
                result = self.reputation.functions.getReputationSummary(agent_id).call()
                return {
                    "agent_id": agent_id,
                    "avg_score": result[0],
                    "feedback_count": result[1],
                    "avg_score_normalized": result[0] / 100.0,
                }
            except Exception:
                return {
                    "agent_id": agent_id,
                    "avg_score": 0,
                    "feedback_count": 0,
                    "avg_score_normalized": 0.0,
                }

        return await trio.to_thread.run_sync(_get)


def trust_score_to_erc8004(score: float) -> int:
    """Convert AgentPay trust score (0.0-1.0) to ERC-8004 (0-100)."""
    clamped = max(0.0, min(1.0, score))
    return round(clamped * 100)


def erc8004_to_trust_score(score: int) -> float:
    """Convert ERC-8004 score (0-100) to AgentPay trust score (0.0-1.0)."""
    return max(0.0, min(1.0, score / 100.0))
