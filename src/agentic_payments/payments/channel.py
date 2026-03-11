"""Payment channel state machine."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto

import structlog

from agentic_payments.payments.voucher import SignedVoucher

logger = structlog.get_logger(__name__)


class ChannelState(Enum):
    """Payment channel lifecycle states."""

    PROPOSED = auto()
    OPEN = auto()
    ACTIVE = auto()
    CLOSING = auto()
    SETTLED = auto()
    DISPUTED = auto()


class ChannelError(Exception):
    """Invalid channel operation."""


@dataclass
class PaymentChannel:
    """Off-chain payment channel between two Ethereum addresses.

    State transitions:
        PROPOSED → OPEN → ACTIVE → CLOSING → SETTLED
                                  → DISPUTED → SETTLED
    """

    channel_id: bytes
    sender: str  # Ethereum address (payer)
    receiver: str  # Ethereum address (payee)
    total_deposit: int  # Wei deposited on-chain
    state: ChannelState = ChannelState.PROPOSED
    nonce: int = 0
    total_paid: int = 0  # Cumulative amount paid
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    latest_voucher: SignedVoucher | None = None
    peer_id: str = ""

    def __post_init__(self) -> None:
        """Validate channel fields at construction time."""
        if not isinstance(self.channel_id, bytes) or len(self.channel_id) != 32:
            raise ChannelError("channel_id must be exactly 32 bytes")
        if not isinstance(self.total_deposit, int) or self.total_deposit <= 0:
            raise ChannelError("total_deposit must be a positive integer")
        if not isinstance(self.total_paid, int) or self.total_paid < 0:
            raise ChannelError("total_paid must be non-negative")
        if self.total_paid > self.total_deposit:
            raise ChannelError("total_paid cannot exceed total_deposit")
        if not isinstance(self.sender, str) or len(self.sender) < 10:
            raise ChannelError("sender must be a valid Ethereum address")
        if not isinstance(self.receiver, str) or len(self.receiver) < 10:
            raise ChannelError("receiver must be a valid Ethereum address")

    def _transition(self, from_states: set[ChannelState], to_state: ChannelState) -> None:
        """Validate and perform a state transition."""
        if self.state not in from_states:
            raise ChannelError(
                f"Cannot transition from {self.state.name} to {to_state.name}. "
                f"Expected one of: {[s.name for s in from_states]}"
            )
        old = self.state
        self.state = to_state
        self.updated_at = int(time.time())
        logger.info(
            "channel_state_transition",
            channel_id=self.channel_id.hex()[:16],
            from_state=old.name,
            to_state=to_state.name,
        )

    def accept(self) -> None:
        """Counterparty accepts the channel open proposal."""
        self._transition({ChannelState.PROPOSED}, ChannelState.OPEN)

    def activate(self) -> None:
        """On-chain deposit confirmed — channel is active for payments."""
        self._transition({ChannelState.OPEN}, ChannelState.ACTIVE)

    def apply_voucher(self, voucher: SignedVoucher) -> None:
        """Apply a signed voucher (micropayment) to the channel.

        Validates nonce ordering and amount bounds.
        """
        if self.state != ChannelState.ACTIVE:
            raise ChannelError(f"Cannot apply voucher in state {self.state.name}")

        if voucher.nonce <= self.nonce:
            raise ChannelError(
                f"Voucher nonce {voucher.nonce} must be > current nonce {self.nonce}"
            )

        if voucher.amount <= self.total_paid:
            raise ChannelError(
                f"Voucher amount {voucher.amount} must be > current total {self.total_paid}"
            )

        if voucher.amount > self.total_deposit:
            raise ChannelError(
                f"Voucher amount {voucher.amount} exceeds deposit {self.total_deposit}"
            )

        self.nonce = voucher.nonce
        self.total_paid = voucher.amount
        self.latest_voucher = voucher
        self.updated_at = int(time.time())
        logger.debug(
            "voucher_applied",
            channel_id=self.channel_id.hex()[:16],
            nonce=voucher.nonce,
            amount=voucher.amount,
        )

    def request_close(self) -> None:
        """Initiate channel close."""
        self._transition({ChannelState.ACTIVE}, ChannelState.CLOSING)

    def settle(self) -> None:
        """Mark channel as settled (on-chain settlement confirmed)."""
        self._transition({ChannelState.CLOSING, ChannelState.DISPUTED}, ChannelState.SETTLED)

    def dispute(self) -> None:
        """Transition to disputed state."""
        self._transition({ChannelState.ACTIVE, ChannelState.CLOSING}, ChannelState.DISPUTED)

    @property
    def remaining_balance(self) -> int:
        """Remaining balance available for payments."""
        return self.total_deposit - self.total_paid

    def to_dict(self) -> dict:
        """Serialize channel state."""
        return {
            "channel_id": self.channel_id.hex(),
            "sender": self.sender,
            "receiver": self.receiver,
            "total_deposit": self.total_deposit,
            "state": self.state.name,
            "nonce": self.nonce,
            "total_paid": self.total_paid,
            "remaining_balance": self.remaining_balance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "peer_id": self.peer_id,
        }
