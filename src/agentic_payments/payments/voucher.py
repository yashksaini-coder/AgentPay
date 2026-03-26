"""Signed payment vouchers (Filecoin-style cumulative amounts)."""

from __future__ import annotations

import time
from dataclasses import dataclass

import structlog
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SignedVoucher:
    """A signed payment voucher for off-chain micropayments.

    Uses cumulative amounts: each voucher replaces the previous one.
    Only the highest-nonce voucher is needed for on-chain settlement.
    """

    channel_id: bytes  # 32-byte channel identifier
    nonce: int  # Monotonically increasing per channel
    amount: int  # Cumulative wei (not incremental)
    timestamp: int  # Unix timestamp
    signature: bytes  # ECDSA signature over the voucher hash
    task_id: str = ""  # Optional: correlate payment to a specific work request

    def __post_init__(self) -> None:
        """Validate voucher fields at construction time."""
        if not isinstance(self.channel_id, bytes) or len(self.channel_id) != 32:
            raise ValueError("channel_id must be exactly 32 bytes")
        if not isinstance(self.nonce, int) or self.nonce < 0:
            raise ValueError("nonce must be a non-negative integer")
        if not isinstance(self.amount, int) or self.amount < 0:
            raise ValueError("amount must be a non-negative integer")
        if not isinstance(self.timestamp, int) or self.timestamp <= 0:
            raise ValueError("timestamp must be a positive integer")
        if not isinstance(self.signature, bytes):
            raise ValueError("signature must be bytes")

    @staticmethod
    def create(
        channel_id: bytes,
        nonce: int,
        amount: int,
        private_key: str,
        task_id: str = "",
    ) -> SignedVoucher:
        """Create and sign a new voucher."""
        ts = int(time.time())
        msg_hash = _voucher_hash(channel_id, nonce, amount, ts)
        signable = encode_defunct(msg_hash)
        signed = Account.sign_message(signable, private_key=private_key)
        return SignedVoucher(
            channel_id=channel_id,
            nonce=nonce,
            amount=amount,
            timestamp=ts,
            signature=signed.signature,
            task_id=task_id,
        )

    def verify(self, expected_signer: str) -> bool:
        """Verify the voucher signature matches the expected signer address."""
        msg_hash = _voucher_hash(self.channel_id, self.nonce, self.amount, self.timestamp)
        signable = encode_defunct(msg_hash)
        try:
            recovered = Account.recover_message(signable, signature=self.signature)
            return recovered.lower() == expected_signer.lower()
        except (ValueError, TypeError) as e:
            logger.debug("voucher_verify_bad_signature", error=str(e))
            return False
        except Exception:
            logger.exception("voucher_verify_unexpected_error")
            return False

    def to_dict(self) -> dict:
        """Serialize to dict for wire transmission (msgpack-compatible, raw bytes)."""
        d = {
            "channel_id": self.channel_id,
            "nonce": self.nonce,
            "amount": self.amount,
            "timestamp": self.timestamp,
            "signature": self.signature,
        }
        if self.task_id:
            d["task_id"] = self.task_id
        return d

    def to_json_dict(self) -> dict:
        """Serialize to JSON-safe dict (hex-encoded bytes)."""
        d = {
            "channel_id": self.channel_id.hex(),
            "nonce": self.nonce,
            "amount": self.amount,
            "timestamp": self.timestamp,
            "signature": self.signature.hex(),
        }
        if self.task_id:
            d["task_id"] = self.task_id
        return d

    @staticmethod
    def from_dict(data: dict) -> SignedVoucher:
        """Deserialize from dict with type validation.

        Handles both raw bytes (from msgpack) and hex strings (from JSON).
        """
        for key in ("channel_id", "nonce", "amount", "timestamp", "signature"):
            if key not in data:
                raise ValueError(f"Missing required voucher field: {key}")
        channel_id = data["channel_id"]
        if isinstance(channel_id, str):
            channel_id = bytes.fromhex(channel_id)
        signature = data["signature"]
        if isinstance(signature, str):
            signature = bytes.fromhex(signature)
        return SignedVoucher(
            channel_id=channel_id,
            nonce=int(data["nonce"]),
            amount=int(data["amount"]),
            timestamp=int(data["timestamp"]),
            signature=signature,
            task_id=data.get("task_id", ""),
        )


def _voucher_hash(channel_id: bytes, nonce: int, amount: int, timestamp: int) -> bytes:
    """Compute the hash that gets signed for a voucher.

    keccak256(abi.encodePacked(channel_id, nonce, amount, timestamp))
    """
    packed = Web3.solidity_keccak(
        ["bytes32", "uint256", "uint256", "uint256"],
        [channel_id, nonce, amount, timestamp],
    )
    return packed
