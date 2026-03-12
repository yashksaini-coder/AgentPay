"""Signed receipt chains for execution reporting."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass

import structlog
from eth_account import Account
from eth_account.messages import encode_defunct

logger = structlog.get_logger(__name__)

GENESIS_HASH = b"\x00" * 32


@dataclass(frozen=True)
class SignedReceipt:
    """An immutable, signed receipt forming a hash chain."""

    receipt_id: bytes
    channel_id: bytes
    nonce: int
    amount: int  # cumulative
    timestamp: float
    sender: str  # eth address
    receiver: str  # eth address
    previous_receipt_hash: bytes
    signature: bytes = b""

    @property
    def receipt_hash(self) -> bytes:
        """SHA-256 hash of this receipt (excluding signature)."""
        data = (
            self.receipt_id
            + self.channel_id
            + self.nonce.to_bytes(8, "big")
            + self.amount.to_bytes(32, "big")
            + int(self.timestamp * 1000).to_bytes(8, "big")
            + self.sender.encode()
            + self.receiver.encode()
            + self.previous_receipt_hash
        )
        return hashlib.sha256(data).digest()

    def to_dict(self) -> dict:
        return {
            "receipt_id": self.receipt_id.hex(),
            "channel_id": self.channel_id.hex(),
            "nonce": self.nonce,
            "amount": self.amount,
            "timestamp": self.timestamp,
            "sender": self.sender,
            "receiver": self.receiver,
            "previous_receipt_hash": self.previous_receipt_hash.hex(),
            "receipt_hash": self.receipt_hash.hex(),
            "signature": self.signature.hex(),
        }

    @staticmethod
    def create(
        channel_id: bytes,
        nonce: int,
        amount: int,
        sender: str,
        receiver: str,
        previous_receipt_hash: bytes,
        private_key: str,
    ) -> SignedReceipt:
        """Create a new signed receipt."""
        receipt = SignedReceipt(
            receipt_id=os.urandom(16),
            channel_id=channel_id,
            nonce=nonce,
            amount=amount,
            timestamp=time.time(),
            sender=sender,
            receiver=receiver,
            previous_receipt_hash=previous_receipt_hash,
        )
        # Sign the receipt hash
        msg = encode_defunct(receipt.receipt_hash)
        signed = Account.sign_message(msg, private_key=private_key)
        return SignedReceipt(
            receipt_id=receipt.receipt_id,
            channel_id=receipt.channel_id,
            nonce=receipt.nonce,
            amount=receipt.amount,
            timestamp=receipt.timestamp,
            sender=receipt.sender,
            receiver=receipt.receiver,
            previous_receipt_hash=receipt.previous_receipt_hash,
            signature=signed.signature,
        )

    def verify(self, expected_signer: str) -> bool:
        """Verify the receipt signature against the expected signer address."""
        try:
            msg = encode_defunct(self.receipt_hash)
            recovered = Account.recover_message(msg, signature=self.signature)
            return recovered.lower() == expected_signer.lower()
        except Exception:
            return False


class ReceiptStore:
    """Stores receipt chains indexed by channel_id."""

    def __init__(self) -> None:
        self._chains: dict[bytes, list[SignedReceipt]] = {}

    def add(self, receipt: SignedReceipt) -> None:
        """Add a receipt to the chain for its channel."""
        chain = self._chains.setdefault(receipt.channel_id, [])
        chain.append(receipt)

    def get_chain(self, channel_id: bytes) -> list[SignedReceipt]:
        """Get the full receipt chain for a channel."""
        return self._chains.get(channel_id, [])

    def get_latest(self, channel_id: bytes) -> SignedReceipt | None:
        """Get the most recent receipt for a channel."""
        chain = self._chains.get(channel_id, [])
        return chain[-1] if chain else None

    def get_previous_hash(self, channel_id: bytes) -> bytes:
        """Get the hash to chain from (genesis if no prior receipts)."""
        latest = self.get_latest(channel_id)
        return latest.receipt_hash if latest else GENESIS_HASH

    def verify_chain(self, channel_id: bytes) -> bool:
        """Verify the integrity of a receipt chain."""
        chain = self.get_chain(channel_id)
        if not chain:
            return True
        # First receipt should chain from genesis
        if chain[0].previous_receipt_hash != GENESIS_HASH:
            return False
        for i in range(1, len(chain)):
            if chain[i].previous_receipt_hash != chain[i - 1].receipt_hash:
                return False
        return True

    def list_channels(self) -> list[bytes]:
        """List all channel IDs with receipts."""
        return list(self._chains.keys())
