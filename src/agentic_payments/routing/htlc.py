"""HTLC (Hash Time-Locked Contract) state management.

Each HTLC locks funds in a payment channel until either:
- The preimage is revealed (fulfill) → funds transfer
- The timeout expires (cancel) → funds return to sender
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass, field
from enum import Enum, auto

import structlog

logger = structlog.get_logger(__name__)


class HtlcState(Enum):
    """HTLC lifecycle states."""

    PENDING = auto()  # Proposed, funds locked
    FULFILLED = auto()  # Preimage revealed, payment complete
    CANCELLED = auto()  # Timed out or routing failure
    EXPIRED = auto()  # Past timeout, awaiting cancellation


class HtlcError(Exception):
    """Invalid HTLC operation."""


@dataclass
class PendingHtlc:
    """An in-flight HTLC on a payment channel."""

    htlc_id: bytes
    channel_id: bytes
    payment_hash: bytes  # SHA-256(preimage)
    amount: int
    timeout: int  # Absolute unix timestamp
    state: HtlcState = HtlcState.PENDING
    # For intermediate hops: the upstream HTLC we need to fulfill
    upstream_htlc_id: bytes | None = None
    upstream_channel_id: bytes | None = None
    # Routing info for next hop (empty = we are the final destination)
    onion_next: bytes = b""
    created_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def is_expired(self) -> bool:
        return int(time.time()) >= self.timeout

    def to_dict(self) -> dict:
        return {
            "htlc_id": self.htlc_id.hex(),
            "channel_id": self.channel_id.hex(),
            "payment_hash": self.payment_hash.hex(),
            "amount": self.amount,
            "timeout": self.timeout,
            "state": self.state.name,
        }


def generate_preimage() -> tuple[bytes, bytes]:
    """Generate a random preimage and its SHA-256 hash.

    Returns: (preimage, payment_hash)
    """
    preimage = os.urandom(32)
    payment_hash = hashlib.sha256(preimage).digest()
    return preimage, payment_hash


def verify_preimage(preimage: bytes, payment_hash: bytes) -> bool:
    """Verify that a preimage matches a payment hash."""
    return hmac.compare_digest(hashlib.sha256(preimage).digest(), payment_hash)


class HtlcManager:
    """Manages pending HTLCs across all channels for this node.

    Tracks both incoming HTLCs (where we are the receiver or forwarder)
    and outgoing HTLCs (where we proposed the HTLC to the next hop).
    """

    def __init__(self) -> None:
        # htlc_id -> PendingHtlc
        self._htlcs: dict[bytes, PendingHtlc] = {}
        # payment_hash -> list of htlc_ids (for preimage propagation)
        self._by_payment_hash: dict[bytes, list[bytes]] = {}

    def add_htlc(self, htlc: PendingHtlc) -> None:
        """Register a new pending HTLC."""
        self._htlcs[htlc.htlc_id] = htlc
        self._by_payment_hash.setdefault(htlc.payment_hash, []).append(htlc.htlc_id)
        logger.debug(
            "htlc_added",
            htlc_id=htlc.htlc_id.hex()[:16],
            amount=htlc.amount,
            timeout=htlc.timeout,
        )

    def get_htlc(self, htlc_id: bytes) -> PendingHtlc:
        """Get an HTLC by ID."""
        htlc = self._htlcs.get(htlc_id)
        if htlc is None:
            raise KeyError(f"HTLC not found: {htlc_id.hex()[:16]}")
        return htlc

    def fulfill(self, htlc_id: bytes, preimage: bytes) -> PendingHtlc:
        """Fulfill an HTLC with its preimage.

        Validates the preimage matches and transitions to FULFILLED.
        Returns the HTLC for upstream propagation.
        """
        htlc = self.get_htlc(htlc_id)

        if htlc.state != HtlcState.PENDING:
            raise HtlcError(f"Cannot fulfill HTLC in state {htlc.state.name}")

        if not verify_preimage(preimage, htlc.payment_hash):
            raise HtlcError("Preimage does not match payment hash")

        htlc.state = HtlcState.FULFILLED
        logger.info(
            "htlc_fulfilled",
            htlc_id=htlc_id.hex()[:16],
            amount=htlc.amount,
        )
        return htlc

    def cancel(self, htlc_id: bytes, reason: str = "") -> PendingHtlc:
        """Cancel a pending HTLC."""
        htlc = self.get_htlc(htlc_id)

        if htlc.state != HtlcState.PENDING:
            raise HtlcError(f"Cannot cancel HTLC in state {htlc.state.name}")

        htlc.state = HtlcState.CANCELLED
        logger.info(
            "htlc_cancelled",
            htlc_id=htlc_id.hex()[:16],
            reason=reason,
        )
        return htlc

    def get_by_payment_hash(self, payment_hash: bytes) -> list[PendingHtlc]:
        """Get all HTLCs for a given payment hash."""
        ids = self._by_payment_hash.get(payment_hash, [])
        return [self._htlcs[hid] for hid in ids if hid in self._htlcs]

    def get_pending_for_channel(self, channel_id: bytes) -> list[PendingHtlc]:
        """Get all pending HTLCs on a specific channel."""
        return [
            h
            for h in self._htlcs.values()
            if h.channel_id == channel_id and h.state == HtlcState.PENDING
        ]

    def pending_amount_for_channel(self, channel_id: bytes) -> int:
        """Total amount locked in pending HTLCs on a channel."""
        return sum(h.amount for h in self.get_pending_for_channel(channel_id))

    def expire_htlcs(self) -> list[PendingHtlc]:
        """Find and mark expired HTLCs. Returns list of newly expired."""
        expired = []
        for htlc in self._htlcs.values():
            if htlc.state == HtlcState.PENDING and htlc.is_expired:
                htlc.state = HtlcState.EXPIRED
                expired.append(htlc)
                logger.warning(
                    "htlc_expired",
                    htlc_id=htlc.htlc_id.hex()[:16],
                    timeout=htlc.timeout,
                )
        return expired

    def cleanup_settled(self) -> int:
        """Remove fulfilled and cancelled HTLCs. Returns count removed."""
        to_remove = [
            hid
            for hid, h in self._htlcs.items()
            if h.state in (HtlcState.FULFILLED, HtlcState.CANCELLED, HtlcState.EXPIRED)
        ]
        for hid in to_remove:
            htlc = self._htlcs.pop(hid)
            ids = self._by_payment_hash.get(htlc.payment_hash, [])
            if hid in ids:
                ids.remove(hid)
        return len(to_remove)
