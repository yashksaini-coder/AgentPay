"""Negotiation state models with machine-readable SLA terms."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class NegotiationState(StrEnum):
    """State machine for a negotiation."""

    PROPOSED = "proposed"
    COUNTERED = "countered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CHANNEL_OPENED = "channel_opened"


@dataclass
class SLATerms:
    """Machine-readable Service Level Agreement terms.

    Attached to negotiations so agents can agree on quality-of-service
    guarantees alongside pricing.
    """

    max_latency_ms: int = 0  # Max response latency in ms (0=unbounded)
    min_availability: float = 0.0  # Min uptime fraction 0.0-1.0
    max_error_rate: float = 1.0  # Max acceptable error rate 0.0-1.0
    min_throughput: int = 0  # Min requests per second (0=unbounded)
    penalty_rate: int = 0  # Wei penalty per SLA violation
    measurement_window: int = 3600  # Window for measuring compliance (seconds)
    dispute_threshold: int = 3  # Violations before auto-dispute

    def to_dict(self) -> dict:
        return {
            "max_latency_ms": self.max_latency_ms,
            "min_availability": self.min_availability,
            "max_error_rate": self.max_error_rate,
            "min_throughput": self.min_throughput,
            "penalty_rate": self.penalty_rate,
            "measurement_window": self.measurement_window,
            "dispute_threshold": self.dispute_threshold,
        }

    @staticmethod
    def from_dict(d: dict) -> SLATerms:
        return SLATerms(
            max_latency_ms=d.get("max_latency_ms", 0),
            min_availability=d.get("min_availability", 0.0),
            max_error_rate=d.get("max_error_rate", 1.0),
            min_throughput=d.get("min_throughput", 0),
            penalty_rate=d.get("penalty_rate", 0),
            measurement_window=d.get("measurement_window", 3600),
            dispute_threshold=d.get("dispute_threshold", 3),
        )


@dataclass
class NegotiationEvent:
    """A single event in the negotiation history."""

    action: str  # propose, counter, accept, reject
    price: int
    by: str  # peer_id of actor
    timestamp: float = field(default_factory=time.time)
    sla_terms: SLATerms | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "action": self.action,
            "price": self.price,
            "by": self.by,
            "timestamp": self.timestamp,
        }
        if self.sla_terms is not None:
            d["sla_terms"] = self.sla_terms.to_dict()
        return d


@dataclass
class Negotiation:
    """A negotiation between two agents over service terms."""

    negotiation_id: str
    initiator: str  # peer_id
    responder: str  # peer_id
    service_type: str
    proposed_price: int
    channel_deposit: int
    timeout: float  # absolute unix timestamp for expiry
    state: NegotiationState = NegotiationState.PROPOSED
    current_price: int | None = None
    channel_id: str | None = None
    history: list[NegotiationEvent] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    sla_terms: SLATerms | None = None

    def __post_init__(self) -> None:
        if self.current_price is None:
            self.current_price = self.proposed_price

    @property
    def is_active(self) -> bool:
        return self.state in (NegotiationState.PROPOSED, NegotiationState.COUNTERED)

    @property
    def is_expired(self) -> bool:
        return self.is_active and time.time() > self.timeout

    def to_dict(self) -> dict:
        d = {
            "negotiation_id": self.negotiation_id,
            "initiator": self.initiator,
            "responder": self.responder,
            "service_type": self.service_type,
            "proposed_price": self.proposed_price,
            "current_price": self.current_price,
            "channel_deposit": self.channel_deposit,
            "timeout": self.timeout,
            "state": self.state.value,
            "channel_id": self.channel_id,
            "history": [e.to_dict() for e in self.history],
            "created_at": self.created_at,
        }
        if self.sla_terms is not None:
            d["sla_terms"] = self.sla_terms.to_dict()
        return d
