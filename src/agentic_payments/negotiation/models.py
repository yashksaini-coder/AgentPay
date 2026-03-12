"""Negotiation state models."""

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
class NegotiationEvent:
    """A single event in the negotiation history."""

    action: str  # propose, counter, accept, reject
    price: int
    by: str  # peer_id of actor
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "price": self.price,
            "by": self.by,
            "timestamp": self.timestamp,
        }


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
    current_price: int = 0
    channel_id: str | None = None
    history: list[NegotiationEvent] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.current_price == 0:
            self.current_price = self.proposed_price

    @property
    def is_active(self) -> bool:
        return self.state in (NegotiationState.PROPOSED, NegotiationState.COUNTERED)

    @property
    def is_expired(self) -> bool:
        return self.is_active and time.time() > self.timeout

    def to_dict(self) -> dict:
        return {
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
