"""Dispute data models."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import StrEnum


class DisputeReason(StrEnum):
    """Why a dispute was filed."""

    STALE_VOUCHER = "stale_voucher"  # Closer used old voucher, we have newer
    SLA_VIOLATION = "sla_violation"  # SLA terms breached beyond threshold
    DOUBLE_SPEND = "double_spend"  # Conflicting vouchers detected
    UNRESPONSIVE = "unresponsive"  # Peer stopped responding during channel


class DisputeResolution(StrEnum):
    """Outcome of a dispute."""

    PENDING = "pending"
    CHALLENGER_WINS = "challenger_wins"
    RESPONDER_WINS = "responder_wins"
    SETTLED = "settled"  # Both parties agreed


@dataclass
class Dispute:
    """A dispute filed against a channel or peer."""

    dispute_id: str = field(default_factory=lambda: os.urandom(16).hex())
    channel_id: bytes = b""
    initiated_by: str = ""  # peer_id of filer
    counterparty: str = ""  # peer_id of other party
    reason: DisputeReason = DisputeReason.STALE_VOUCHER
    evidence_nonce: int = 0  # Our highest nonce as evidence
    evidence_amount: int = 0  # Our highest amount as evidence
    resolution: DisputeResolution = DisputeResolution.PENDING
    slash_amount: int = 0  # Wei slashed from counterparty
    created_at: float = field(default_factory=time.time)
    resolved_at: float = 0.0
    challenge_tx: str = ""  # On-chain challenge tx hash

    def to_dict(self) -> dict:
        return {
            "dispute_id": self.dispute_id,
            "channel_id": self.channel_id.hex() if self.channel_id else "",
            "initiated_by": self.initiated_by,
            "counterparty": self.counterparty,
            "reason": self.reason.value,
            "evidence_nonce": self.evidence_nonce,
            "evidence_amount": self.evidence_amount,
            "resolution": self.resolution.value,
            "slash_amount": self.slash_amount,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "challenge_tx": self.challenge_tx,
        }

    @staticmethod
    def from_dict(d: dict) -> Dispute:
        channel_id = d.get("channel_id", "")
        if isinstance(channel_id, str) and channel_id:
            channel_id = bytes.fromhex(channel_id)
        elif not isinstance(channel_id, bytes):
            channel_id = b""
        return Dispute(
            dispute_id=d.get("dispute_id", os.urandom(16).hex()),
            channel_id=channel_id,
            initiated_by=d.get("initiated_by", ""),
            counterparty=d.get("counterparty", ""),
            reason=DisputeReason(d.get("reason", "stale_voucher")),
            evidence_nonce=d.get("evidence_nonce", 0),
            evidence_amount=d.get("evidence_amount", 0),
            resolution=DisputeResolution(d.get("resolution", "pending")),
            slash_amount=d.get("slash_amount", 0),
            created_at=d.get("created_at", time.time()),
            resolved_at=d.get("resolved_at", 0.0),
            challenge_tx=d.get("challenge_tx", ""),
        )
