"""PaymentChannel Solidity ABI + web3.py bindings."""

from __future__ import annotations

from typing import Any

from web3 import Web3
from web3.contract import Contract

# PaymentChannel ABI — matches contracts/src/PaymentChannel.sol
PAYMENT_CHANNEL_ABI = [
    # openChannel (ETH)
    {
        "inputs": [
            {"name": "receiver", "type": "address"},
            {"name": "duration", "type": "uint256"},
        ],
        "name": "openChannel",
        "outputs": [{"name": "channelId", "type": "bytes32"}],
        "stateMutability": "payable",
        "type": "function",
    },
    # openTokenChannel (ERC-20)
    {
        "inputs": [
            {"name": "receiver", "type": "address"},
            {"name": "duration", "type": "uint256"},
            {"name": "token", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "openTokenChannel",
        "outputs": [{"name": "channelId", "type": "bytes32"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # closeChannel
    {
        "inputs": [
            {"name": "channelId", "type": "bytes32"},
            {"name": "amount", "type": "uint256"},
            {"name": "nonce", "type": "uint256"},
            {"name": "timestamp", "type": "uint256"},
            {"name": "signature", "type": "bytes"},
        ],
        "name": "closeChannel",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # challengeClose
    {
        "inputs": [
            {"name": "channelId", "type": "bytes32"},
            {"name": "amount", "type": "uint256"},
            {"name": "nonce", "type": "uint256"},
            {"name": "timestamp", "type": "uint256"},
            {"name": "signature", "type": "bytes"},
        ],
        "name": "challengeClose",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # withdraw
    {
        "inputs": [{"name": "channelId", "type": "bytes32"}],
        "name": "withdraw",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # getChannel
    {
        "inputs": [{"name": "channelId", "type": "bytes32"}],
        "name": "getChannel",
        "outputs": [
            {"name": "sender", "type": "address"},
            {"name": "receiver", "type": "address"},
            {"name": "deposit", "type": "uint256"},
            {"name": "closingNonce", "type": "uint256"},
            {"name": "closingAmount", "type": "uint256"},
            {"name": "expiration", "type": "uint256"},
            {"name": "closed", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    # getChannelToken
    {
        "inputs": [{"name": "channelId", "type": "bytes32"}],
        "name": "getChannelToken",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    # Events
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "channelId", "type": "bytes32"},
            {"indexed": True, "name": "sender", "type": "address"},
            {"indexed": True, "name": "receiver", "type": "address"},
            {"indexed": False, "name": "deposit", "type": "uint256"},
        ],
        "name": "ChannelOpened",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "channelId", "type": "bytes32"},
            {"indexed": True, "name": "sender", "type": "address"},
            {"indexed": True, "name": "receiver", "type": "address"},
            {"indexed": False, "name": "deposit", "type": "uint256"},
            {"indexed": False, "name": "token", "type": "address"},
        ],
        "name": "TokenChannelOpened",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "channelId", "type": "bytes32"},
            {"indexed": False, "name": "amount", "type": "uint256"},
            {"indexed": False, "name": "expiration", "type": "uint256"},
        ],
        "name": "ChannelCloseInitiated",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "channelId", "type": "bytes32"},
            {"indexed": False, "name": "amount", "type": "uint256"},
            {"indexed": False, "name": "nonce", "type": "uint256"},
        ],
        "name": "ChannelChallenged",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "channelId", "type": "bytes32"},
            {"indexed": False, "name": "amount", "type": "uint256"},
        ],
        "name": "ChannelClosed",
        "type": "event",
    },
]


def get_payment_channel_contract(w3: Web3, address: str) -> Contract:
    """Get a web3 contract instance for the PaymentChannel contract."""
    return w3.eth.contract(
        address=Web3.to_checksum_address(address),
        abi=PAYMENT_CHANNEL_ABI,
    )


def build_open_channel_tx(
    contract: Contract,
    receiver: str,
    duration: int,
    deposit_wei: int,
    sender: str,
    nonce: int,
    gas_price: int | None = None,
) -> dict[str, Any]:
    """Build an openChannel transaction (native ETH)."""
    tx = contract.functions.openChannel(
        Web3.to_checksum_address(receiver),
        duration,
    ).build_transaction(
        {  # type: ignore[arg-type]
            "from": sender,
            "value": deposit_wei,
            "nonce": nonce,
            **({"gasPrice": gas_price} if gas_price else {}),  # type: ignore[typeddict-item]
        }
    )
    return tx  # type: ignore[return-value]


def build_open_token_channel_tx(
    contract: Contract,
    receiver: str,
    duration: int,
    token_address: str,
    amount: int,
    sender: str,
    nonce: int,
) -> dict[str, Any]:
    """Build an openTokenChannel transaction (ERC-20 token)."""
    tx = contract.functions.openTokenChannel(
        Web3.to_checksum_address(receiver),
        duration,
        Web3.to_checksum_address(token_address),
        amount,
    ).build_transaction(
        {  # type: ignore[arg-type]
            "from": sender,
            "nonce": nonce,
        }
    )
    return tx  # type: ignore[return-value]


def build_close_channel_tx(
    contract: Contract,
    channel_id: bytes,
    amount: int,
    nonce: int,
    timestamp: int,
    signature: bytes,
    sender: str,
    tx_nonce: int,
) -> dict[str, Any]:
    """Build a closeChannel transaction."""
    tx = contract.functions.closeChannel(
        channel_id, amount, nonce, timestamp, signature
    ).build_transaction(
        {  # type: ignore[arg-type]
            "from": sender,
            "nonce": tx_nonce,
        }
    )
    return tx  # type: ignore[return-value]
