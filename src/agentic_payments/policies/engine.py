"""Wallet policy engine for automated spending controls."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


class PolicyViolation(Exception):
    """Raised when a payment violates wallet policy."""


@dataclass
class WalletPolicy:
    """Spending policy for an agent's wallet."""

    max_spend_per_tx: int = 0  # 0 = unlimited
    max_total_spend: int = 0  # 0 = unlimited
    rate_limit_per_min: int = 0  # 0 = unlimited
    peer_whitelist: list[str] = field(default_factory=list)
    peer_blacklist: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "max_spend_per_tx": self.max_spend_per_tx,
            "max_total_spend": self.max_total_spend,
            "rate_limit_per_min": self.rate_limit_per_min,
            "peer_whitelist": self.peer_whitelist,
            "peer_blacklist": self.peer_blacklist,
        }

    @staticmethod
    def from_dict(d: dict) -> WalletPolicy:
        return WalletPolicy(
            max_spend_per_tx=d.get("max_spend_per_tx", 0),
            max_total_spend=d.get("max_total_spend", 0),
            rate_limit_per_min=d.get("rate_limit_per_min", 0),
            peer_whitelist=d.get("peer_whitelist", []),
            peer_blacklist=d.get("peer_blacklist", []),
        )


class PolicyEngine:
    """Enforces wallet spending policies."""

    def __init__(self, policy: WalletPolicy | None = None) -> None:
        self.policy = policy or WalletPolicy()
        self._total_spent: int = 0
        self._payment_timestamps: deque[float] = deque()

    def check_payment(self, amount: int, peer_id: str) -> None:
        """Check if a payment is allowed by policy. Raises PolicyViolation if not."""
        p = self.policy

        # Per-tx limit
        if p.max_spend_per_tx > 0 and amount > p.max_spend_per_tx:
            raise PolicyViolation(
                f"Amount {amount} exceeds per-transaction limit {p.max_spend_per_tx}"
            )

        # Total spend limit
        if p.max_total_spend > 0 and (self._total_spent + amount) > p.max_total_spend:
            raise PolicyViolation(
                f"Total spend would be {self._total_spent + amount}, "
                f"exceeding limit {p.max_total_spend}"
            )

        # Rate limit
        if p.rate_limit_per_min > 0:
            now = time.time()
            cutoff = now - 60.0
            while self._payment_timestamps and self._payment_timestamps[0] < cutoff:
                self._payment_timestamps.popleft()
            if len(self._payment_timestamps) >= p.rate_limit_per_min:
                raise PolicyViolation(
                    f"Rate limit exceeded: {p.rate_limit_per_min} payments per minute"
                )

        # Peer whitelist (if set, only whitelisted peers allowed)
        if p.peer_whitelist and peer_id not in p.peer_whitelist:
            raise PolicyViolation(f"Peer {peer_id} not in whitelist")

        # Peer blacklist
        if peer_id in p.peer_blacklist:
            raise PolicyViolation(f"Peer {peer_id} is blacklisted")

    def check_channel_open(self, deposit: int, peer_id: str) -> None:
        """Check if opening a channel is allowed by policy."""
        p = self.policy

        # Peer blacklist
        if peer_id in p.peer_blacklist:
            raise PolicyViolation(f"Peer {peer_id} is blacklisted")

        # Whitelist check
        if p.peer_whitelist and peer_id not in p.peer_whitelist:
            raise PolicyViolation(f"Peer {peer_id} not in whitelist")

        # Total spend check (deposit counts toward total)
        if p.max_total_spend > 0 and (self._total_spent + deposit) > p.max_total_spend:
            raise PolicyViolation(
                f"Channel deposit {deposit} would exceed total spend limit {p.max_total_spend}"
            )

    def record_payment(self, amount: int) -> None:
        """Record a successful payment for rate/total tracking."""
        self._total_spent += amount
        self._payment_timestamps.append(time.time())

    def record_channel_open(self, amount: int) -> None:
        """Record a channel deposit for total spend tracking."""
        self.record_payment(amount)

    def get_stats(self) -> dict:
        """Return current spending statistics."""
        now = time.time()
        cutoff = now - 60.0
        while self._payment_timestamps and self._payment_timestamps[0] < cutoff:
            self._payment_timestamps.popleft()
        return {
            "total_spent": self._total_spent,
            "payments_last_minute": len(self._payment_timestamps),
            "policy": self.policy.to_dict(),
        }

    def update_policy(self, policy: WalletPolicy) -> None:
        """Update the active policy."""
        self.policy = policy
        logger.info("policy_updated", policy=policy.to_dict())
