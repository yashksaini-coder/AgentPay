"""Dispute monitor: scans for channels that need challenging."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

from agentic_payments.disputes.models import (
    Dispute,
    DisputeReason,
    DisputeResolution,
)
from agentic_payments.payments.channel import ChannelState

if TYPE_CHECKING:
    from agentic_payments.payments.manager import ChannelManager
    from agentic_payments.reputation.tracker import ReputationTracker

logger = structlog.get_logger(__name__)

DEFAULT_SCAN_INTERVAL = 30  # seconds
DEFAULT_SLASH_PERCENTAGE = 0.10  # 10% of deposit


class DisputeMonitor:
    """Monitors channels and auto-files disputes when stale vouchers are detected."""

    def __init__(
        self,
        channel_manager: ChannelManager,
        reputation_tracker: ReputationTracker | None = None,
        auto_challenge: bool = True,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        slash_percentage: float = DEFAULT_SLASH_PERCENTAGE,
    ) -> None:
        self.channel_manager = channel_manager
        self.reputation = reputation_tracker
        self.auto_challenge = auto_challenge
        self.scan_interval = scan_interval
        self.slash_percentage = slash_percentage
        self._disputes: dict[str, Dispute] = {}

    def scan_channels(self) -> list[Dispute]:
        """Scan all CLOSING/DISPUTED channels for challenge opportunities.

        Returns list of newly created disputes.
        """
        new_disputes: list[Dispute] = []
        local_addr = self.channel_manager.local_address

        for ch in self.channel_manager.list_channels():
            if ch.state not in (ChannelState.CLOSING, ChannelState.DISPUTED):
                continue

            # We're the receiver and we have a higher nonce than the closing nonce
            if ch.receiver == local_addr and ch.nonce > ch.closing_nonce:
                # Check if we already have a dispute for this channel
                existing = self._find_dispute_for_channel(ch.channel_id)
                if existing is not None:
                    continue

                slash = int(ch.total_deposit * self.slash_percentage)
                dispute = Dispute(
                    channel_id=ch.channel_id,
                    initiated_by=local_addr,
                    counterparty=ch.sender,
                    reason=DisputeReason.STALE_VOUCHER,
                    evidence_nonce=ch.nonce,
                    evidence_amount=ch.total_paid,
                    slash_amount=slash,
                )
                self._disputes[dispute.dispute_id] = dispute
                new_disputes.append(dispute)

                logger.info(
                    "dispute_detected",
                    channel=ch.channel_id.hex()[:12],
                    our_nonce=ch.nonce,
                    closing_nonce=ch.closing_nonce,
                    slash=slash,
                )

                # Penalize trust score
                if self.reputation and ch.peer_id:
                    self.reputation.record_payment_failed(ch.peer_id)

        return new_disputes

    def file_dispute(
        self,
        channel_id: bytes,
        reason: DisputeReason,
        initiated_by: str,
        counterparty: str,
        evidence_nonce: int = 0,
        evidence_amount: int = 0,
    ) -> Dispute:
        """Manually file a dispute for a channel."""
        ch = self.channel_manager.get_channel(channel_id)
        if ch is None:
            raise KeyError(f"Channel not found: {channel_id.hex()}")
        slash = int(ch.total_deposit * self.slash_percentage)

        dispute = Dispute(
            channel_id=channel_id,
            initiated_by=initiated_by,
            counterparty=counterparty,
            reason=reason,
            evidence_nonce=evidence_nonce or ch.nonce,
            evidence_amount=evidence_amount or ch.total_paid,
            slash_amount=slash,
        )
        self._disputes[dispute.dispute_id] = dispute
        logger.info("dispute_filed", id=dispute.dispute_id[:12], reason=reason.value)
        return dispute

    def resolve_dispute(self, dispute_id: str, resolution: DisputeResolution) -> Dispute:
        """Resolve an existing dispute."""
        dispute = self.get_dispute(dispute_id)
        dispute.resolution = resolution
        dispute.resolved_at = time.time()

        # Update trust based on outcome
        if self.reputation and dispute.counterparty:
            if resolution == DisputeResolution.CHALLENGER_WINS:
                self.reputation.record_payment_failed(dispute.counterparty)
            elif resolution == DisputeResolution.RESPONDER_WINS:
                self.reputation.record_payment_failed(dispute.initiated_by)

        logger.info("dispute_resolved", id=dispute_id[:12], resolution=resolution.value)
        return dispute

    def get_dispute(self, dispute_id: str) -> Dispute:
        """Get a dispute by ID."""
        dispute = self._disputes.get(dispute_id)
        if dispute is None:
            raise KeyError(f"Dispute not found: {dispute_id}")
        return dispute

    def list_disputes(self, pending_only: bool = False) -> list[Dispute]:
        """List all disputes, optionally filtered to pending only."""
        disputes = list(self._disputes.values())
        if pending_only:
            disputes = [d for d in disputes if d.resolution == DisputeResolution.PENDING]
        return disputes

    def _find_dispute_for_channel(self, channel_id: bytes) -> Dispute | None:
        """Find an existing dispute for a channel."""
        for d in self._disputes.values():
            if d.channel_id == channel_id and d.resolution == DisputeResolution.PENDING:
                return d
        return None
