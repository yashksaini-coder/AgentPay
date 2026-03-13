"""Negotiation manager for multi-step service term agreements."""

from __future__ import annotations

import os
import time

import structlog

from agentic_payments.negotiation.models import (
    Negotiation,
    NegotiationEvent,
    NegotiationState,
    SLATerms,
)

logger = structlog.get_logger(__name__)

DEFAULT_TIMEOUT = 300  # 5 minutes


class NegotiationManager:
    """Manages negotiations between agents."""

    def __init__(self) -> None:
        self._negotiations: dict[str, Negotiation] = {}

    def propose(
        self,
        initiator: str,
        responder: str,
        service_type: str,
        proposed_price: int,
        channel_deposit: int,
        timeout: float | None = None,
        sla_terms: SLATerms | None = None,
    ) -> Negotiation:
        """Create a new negotiation proposal with optional SLA terms."""
        nid = os.urandom(16).hex()
        if timeout is None:
            timeout = time.time() + DEFAULT_TIMEOUT

        neg = Negotiation(
            negotiation_id=nid,
            initiator=initiator,
            responder=responder,
            service_type=service_type,
            proposed_price=proposed_price,
            channel_deposit=channel_deposit,
            timeout=timeout,
            sla_terms=sla_terms,
        )
        neg.history.append(
            NegotiationEvent(action="propose", price=proposed_price, by=initiator, sla_terms=sla_terms)
        )
        self._negotiations[nid] = neg
        logger.info("negotiation_proposed", id=nid[:12], service=service_type, price=proposed_price)
        return neg

    def counter(
        self, negotiation_id: str, by: str, counter_price: int, sla_terms: SLATerms | None = None,
    ) -> Negotiation:
        """Submit a counter-offer with optional SLA term modifications."""
        neg = self._get_active(negotiation_id)
        if by not in (neg.initiator, neg.responder):
            raise ValueError("Only participants can counter")
        neg.state = NegotiationState.COUNTERED
        neg.current_price = counter_price
        if sla_terms is not None:
            neg.sla_terms = sla_terms
        neg.history.append(
            NegotiationEvent(action="counter", price=counter_price, by=by, sla_terms=sla_terms)
        )
        logger.info("negotiation_countered", id=negotiation_id[:12], price=counter_price)
        return neg

    def accept(self, negotiation_id: str, by: str) -> Negotiation:
        """Accept the current terms."""
        neg = self._get_active(negotiation_id)
        if by not in (neg.initiator, neg.responder):
            raise ValueError("Only participants can accept")
        neg.state = NegotiationState.ACCEPTED
        neg.history.append(
            NegotiationEvent(action="accept", price=neg.current_price, by=by)
        )
        logger.info("negotiation_accepted", id=negotiation_id[:12], price=neg.current_price)
        return neg

    def reject(self, negotiation_id: str, by: str) -> Negotiation:
        """Reject the negotiation."""
        neg = self._get_active(negotiation_id)
        if by not in (neg.initiator, neg.responder):
            raise ValueError("Only participants can reject")
        neg.state = NegotiationState.REJECTED
        neg.history.append(
            NegotiationEvent(action="reject", price=neg.current_price, by=by)
        )
        logger.info("negotiation_rejected", id=negotiation_id[:12])
        return neg

    def link_channel(self, negotiation_id: str, channel_id: str) -> Negotiation:
        """Link an opened channel to an accepted negotiation."""
        neg = self.get(negotiation_id)
        if neg.state != NegotiationState.ACCEPTED:
            raise ValueError(f"Cannot link channel: negotiation is {neg.state}")
        neg.channel_id = channel_id
        neg.state = NegotiationState.CHANNEL_OPENED
        logger.info("negotiation_channel_linked", id=negotiation_id[:12], channel=channel_id[:12])
        return neg

    def get(self, negotiation_id: str) -> Negotiation:
        """Get a negotiation by ID."""
        neg = self._negotiations.get(negotiation_id)
        if neg is None:
            raise KeyError(f"Negotiation not found: {negotiation_id}")
        # Check expiry
        if neg.is_expired:
            neg.state = NegotiationState.EXPIRED
        return neg

    def list_active(self) -> list[Negotiation]:
        """List all active (non-terminal) negotiations."""
        result = []
        for neg in self._negotiations.values():
            if neg.is_expired:
                neg.state = NegotiationState.EXPIRED
            if neg.is_active:
                result.append(neg)
        return result

    def list_all(self) -> list[Negotiation]:
        """List all negotiations."""
        for neg in self._negotiations.values():
            if neg.is_expired:
                neg.state = NegotiationState.EXPIRED
        return list(self._negotiations.values())

    def _get_active(self, negotiation_id: str) -> Negotiation:
        """Get a negotiation that must be in an active state."""
        neg = self.get(negotiation_id)
        if not neg.is_active:
            raise ValueError(f"Negotiation {negotiation_id} is not active (state={neg.state})")
        return neg
