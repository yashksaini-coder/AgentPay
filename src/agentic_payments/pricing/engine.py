"""Dynamic pricing engine: adjusts prices based on trust and congestion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from agentic_payments.payments.manager import ChannelManager
    from agentic_payments.reputation.tracker import ReputationTracker

logger = structlog.get_logger(__name__)


@dataclass
class PricingPolicy:
    """Controls how dynamic pricing adjusts base prices."""

    trust_discount_factor: float = 0.3  # Max discount for perfect trust (30%)
    congestion_premium_factor: float = 0.5  # Max premium at full congestion (50%)
    min_price: int = 0  # Price floor (wei)
    max_price: int = 0  # Price ceiling (0=unlimited)
    congestion_threshold: int = 20  # Number of active channels = "full congestion"

    def to_dict(self) -> dict:
        return {
            "trust_discount_factor": self.trust_discount_factor,
            "congestion_premium_factor": self.congestion_premium_factor,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "congestion_threshold": self.congestion_threshold,
        }

    @staticmethod
    def from_dict(d: dict) -> PricingPolicy:
        return PricingPolicy(
            trust_discount_factor=d.get("trust_discount_factor", 0.3),
            congestion_premium_factor=d.get("congestion_premium_factor", 0.5),
            min_price=d.get("min_price", 0),
            max_price=d.get("max_price", 0),
            congestion_threshold=d.get("congestion_threshold", 20),
        )


class PricingEngine:
    """Computes dynamic prices based on peer trust and network load."""

    def __init__(
        self,
        reputation_tracker: ReputationTracker,
        channel_manager: ChannelManager | None = None,
        policy: PricingPolicy | None = None,
    ) -> None:
        self.reputation = reputation_tracker
        self.channel_manager = channel_manager
        self.policy = policy or PricingPolicy()

    def compute_price(self, base_price: int, peer_id: str) -> int:
        """Compute dynamic price for a peer.

        Higher trust → lower price (discount).
        Higher congestion → higher price (premium).
        """
        trust_score = self.reputation.get_trust_score(peer_id)
        congestion = self._congestion_ratio()

        # Trust discount: trust=1.0 → full discount, trust=0.0 → no discount
        discount = self.policy.trust_discount_factor * trust_score
        # Congestion premium: congestion=1.0 → full premium, congestion=0.0 → no premium
        premium = self.policy.congestion_premium_factor * congestion

        multiplier = 1.0 - discount + premium
        price = int(base_price * max(multiplier, 0.1))  # Never below 10% of base

        # Apply floor/ceiling
        if self.policy.min_price > 0:
            price = max(price, self.policy.min_price)
        if self.policy.max_price > 0:
            price = min(price, self.policy.max_price)

        logger.debug(
            "dynamic_price",
            base=base_price,
            computed=price,
            trust=round(trust_score, 3),
            congestion=round(congestion, 3),
            discount=round(discount, 3),
            premium=round(premium, 3),
        )
        return price

    def get_quote(self, base_price: int, peer_id: str) -> dict:
        """Get a detailed pricing quote with breakdown."""
        trust_score = self.reputation.get_trust_score(peer_id)
        congestion = self._congestion_ratio()
        final_price = self.compute_price(base_price, peer_id)

        return {
            "base_price": base_price,
            "final_price": final_price,
            "peer_id": peer_id,
            "trust_score": round(trust_score, 4),
            "congestion_ratio": round(congestion, 4),
            "trust_discount_pct": round(self.policy.trust_discount_factor * trust_score * 100, 1),
            "congestion_premium_pct": round(self.policy.congestion_premium_factor * congestion * 100, 1),
            "policy": self.policy.to_dict(),
        }

    def update_policy(self, policy: PricingPolicy) -> None:
        """Update the pricing policy."""
        self.policy = policy
        logger.info("pricing_policy_updated", policy=policy.to_dict())

    def _congestion_ratio(self) -> float:
        """Compute current network congestion as 0.0-1.0 ratio."""
        if self.channel_manager is None or self.policy.congestion_threshold <= 0:
            return 0.0
        from agentic_payments.payments.channel import ChannelState

        active = len(self.channel_manager.list_channels(state=ChannelState.ACTIVE))
        return min(active / self.policy.congestion_threshold, 1.0)
