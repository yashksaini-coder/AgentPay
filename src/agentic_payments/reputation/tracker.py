"""Peer reputation tracker with trust scoring."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)

# Weights for trust score formula
W_SUCCESS = 0.4
W_VOLUME = 0.3
W_SPEED = 0.2
W_LONGEVITY = 0.1

# Normalization constants
VOLUME_NORM = 10_000_000_000_000_000_000  # 10 ETH in wei
SPEED_IDEAL = 1.0  # 1 second response time = perfect score
LONGEVITY_NORM = 86400 * 30  # 30 days


@dataclass
class PeerReputation:
    """Reputation data for a single peer."""

    peer_id: str
    payments_sent: int = 0
    payments_received: int = 0
    payments_failed: int = 0
    htlcs_fulfilled: int = 0
    htlcs_cancelled: int = 0
    total_volume: int = 0  # wei
    response_times: list[float] = field(default_factory=list)
    first_seen: float = field(default_factory=time.time)

    @property
    def total_interactions(self) -> int:
        return (
            self.payments_sent
            + self.payments_received
            + self.htlcs_fulfilled
            + self.htlcs_cancelled
        )

    @property
    def success_rate(self) -> float:
        total = self.payments_sent + self.payments_failed
        if total == 0:
            return 0.5  # neutral default
        return self.payments_sent / total

    @property
    def avg_response_time(self) -> float:
        if not self.response_times:
            return SPEED_IDEAL  # neutral default
        return sum(self.response_times) / len(self.response_times)

    @property
    def trust_score(self) -> float:
        """Compute trust score: 0.0 (untrusted) to 1.0 (fully trusted).

        Formula: 0.4*success + 0.3*volume + 0.2*speed + 0.1*longevity
        """
        success = self.success_rate
        volume = min(self.total_volume / VOLUME_NORM, 1.0)
        speed = min(SPEED_IDEAL / max(self.avg_response_time, 0.01), 1.0)
        longevity = min((time.time() - self.first_seen) / LONGEVITY_NORM, 1.0)
        return W_SUCCESS * success + W_VOLUME * volume + W_SPEED * speed + W_LONGEVITY * longevity

    def to_dict(self) -> dict:
        return {
            "peer_id": self.peer_id,
            "payments_sent": self.payments_sent,
            "payments_received": self.payments_received,
            "payments_failed": self.payments_failed,
            "htlcs_fulfilled": self.htlcs_fulfilled,
            "htlcs_cancelled": self.htlcs_cancelled,
            "total_volume": self.total_volume,
            "avg_response_time": round(self.avg_response_time, 3),
            "trust_score": round(self.trust_score, 4),
            "total_interactions": self.total_interactions,
            "first_seen": self.first_seen,
        }


class ReputationTracker:
    """Tracks reputation for all known peers."""

    def __init__(self) -> None:
        self._peers: dict[str, PeerReputation] = {}

    def _get_or_create(self, peer_id: str) -> PeerReputation:
        rep = self._peers.get(peer_id)
        if rep is None:
            rep = PeerReputation(peer_id=peer_id)
            self._peers[peer_id] = rep
        return rep

    def record_payment_sent(self, peer_id: str, amount: int, response_time: float = 0.0) -> None:
        rep = self._get_or_create(peer_id)
        rep.payments_sent += 1
        rep.total_volume += amount
        if response_time > 0:
            rep.response_times.append(response_time)
            # Keep only last 100 response times
            if len(rep.response_times) > 100:
                rep.response_times = rep.response_times[-100:]

    def record_payment_received(self, peer_id: str, amount: int) -> None:
        rep = self._get_or_create(peer_id)
        rep.payments_received += 1
        rep.total_volume += amount

    def record_payment_failed(self, peer_id: str) -> None:
        rep = self._get_or_create(peer_id)
        rep.payments_failed += 1

    def record_htlc_fulfilled(self, peer_id: str, response_time: float = 0.0) -> None:
        rep = self._get_or_create(peer_id)
        rep.htlcs_fulfilled += 1
        if response_time > 0:
            rep.response_times.append(response_time)
            if len(rep.response_times) > 100:
                rep.response_times = rep.response_times[-100:]

    def record_htlc_cancelled(self, peer_id: str) -> None:
        rep = self._get_or_create(peer_id)
        rep.htlcs_cancelled += 1

    def get_reputation(self, peer_id: str) -> PeerReputation | None:
        return self._peers.get(peer_id)

    def get_all(self) -> list[PeerReputation]:
        return list(self._peers.values())

    def get_trust_score(self, peer_id: str) -> float:
        rep = self._peers.get(peer_id)
        if rep is None:
            return 0.5  # neutral for unknown peers
        return rep.trust_score
