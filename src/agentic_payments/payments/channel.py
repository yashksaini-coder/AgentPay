"""Payment channel state machine."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto

import structlog

from agentic_payments.payments.voucher import SignedVoucher

logger = structlog.get_logger(__name__)

# Default challenge period for on-chain settlement (1 hour, matches contract)
DEFAULT_CHALLENGE_PERIOD = 3600


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

    The close flow enforces a challenge period:
    1. request_close() transitions to CLOSING and records expiration
    2. During the challenge period, dispute() can submit a higher-nonce voucher
    3. settle() only succeeds after the challenge period has elapsed
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
    pending_htlc_amount: int = 0  # Wei locked in pending HTLCs
    # Challenge period tracking
    challenge_period: int = DEFAULT_CHALLENGE_PERIOD
    close_initiated_at: int = 0  # When close was requested (unix timestamp)
    close_expiration: int = 0  # When challenge period expires
    closing_nonce: int = 0  # Nonce submitted for on-chain close
    closing_amount: int = 0  # Amount submitted for on-chain close
    # On-chain settlement info
    on_chain_tx: str = ""  # Settlement tx hash (if settled on-chain)
    token_address: str = ""  # ERC-20 token address (empty = native ETH)
    chain_type: str = "ethereum"  # "ethereum" or "algorand"
    sla_terms: dict | None = None  # Negotiated SLA terms (from negotiation)
    dispute_reason: str = ""  # Reason if disputed

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
        """Initiate channel close with challenge period enforcement.

        Records the closing state with the current voucher info and sets
        the expiration timestamp. During the challenge period, the counterparty
        can dispute with a higher-nonce voucher.
        """
        self._transition({ChannelState.ACTIVE}, ChannelState.CLOSING)
        now = int(time.time())
        self.close_initiated_at = now
        self.close_expiration = now + self.challenge_period
        self.closing_nonce = self.nonce
        self.closing_amount = self.total_paid
        logger.info(
            "channel_close_initiated",
            channel_id=self.channel_id.hex()[:16],
            expiration=self.close_expiration,
            closing_nonce=self.closing_nonce,
            closing_amount=self.closing_amount,
        )

    def dispute(self, voucher: SignedVoucher | None = None) -> None:
        """Dispute a closing channel with a higher-nonce voucher.

        Can be called during the challenge period to submit evidence of
        a higher-nonce state. Resets the challenge timer.
        """
        self._transition({ChannelState.ACTIVE, ChannelState.CLOSING}, ChannelState.DISPUTED)

        if voucher is not None:
            if voucher.nonce <= self.closing_nonce:
                raise ChannelError(
                    f"Dispute voucher nonce {voucher.nonce} must be > "
                    f"closing nonce {self.closing_nonce}"
                )
            self.closing_nonce = voucher.nonce
            self.closing_amount = voucher.amount
            self.latest_voucher = voucher
            self.nonce = voucher.nonce
            self.total_paid = voucher.amount

        # Reset challenge period
        now = int(time.time())
        self.close_expiration = now + self.challenge_period
        logger.info(
            "channel_disputed",
            channel_id=self.channel_id.hex()[:16],
            new_nonce=self.closing_nonce,
            new_expiration=self.close_expiration,
        )

    @property
    def challenge_expired(self) -> bool:
        """Whether the challenge period has elapsed."""
        if self.close_expiration == 0:
            return False
        return int(time.time()) >= self.close_expiration

    def settle(self, tx_hash: str = "") -> None:
        """Mark channel as settled after challenge period.

        Enforces that the challenge period has elapsed before allowing settlement.
        For cooperative closes where both parties agree, challenge_period can be
        set to 0 at close time.
        """
        if self.state in (ChannelState.CLOSING, ChannelState.DISPUTED):
            if self.close_expiration > 0 and not self.challenge_expired:
                remaining = self.close_expiration - int(time.time())
                raise ChannelError(
                    f"Challenge period still active ({remaining}s remaining). "
                    f"Cannot settle until {self.close_expiration}"
                )
        self._transition({ChannelState.CLOSING, ChannelState.DISPUTED}, ChannelState.SETTLED)
        if tx_hash:
            self.on_chain_tx = tx_hash

    def cooperative_close(self) -> None:
        """Fast cooperative close — both parties agree, no challenge period needed.

        Transitions directly to CLOSING with zero challenge period,
        allowing immediate settlement.
        """
        self._transition({ChannelState.ACTIVE}, ChannelState.CLOSING)
        now = int(time.time())
        self.close_initiated_at = now
        self.close_expiration = now  # Expires immediately
        self.closing_nonce = self.nonce
        self.closing_amount = self.total_paid
        logger.info(
            "channel_cooperative_close",
            channel_id=self.channel_id.hex()[:16],
            nonce=self.closing_nonce,
            amount=self.closing_amount,
        )

    def lock_htlc(self, amount: int) -> None:
        """Lock funds for a pending HTLC."""
        if self.state != ChannelState.ACTIVE:
            raise ChannelError(f"Cannot lock HTLC in state {self.state.name}")
        if amount > self.available_balance:
            raise ChannelError(
                f"Insufficient balance: need {amount}, available {self.available_balance}"
            )
        self.pending_htlc_amount += amount
        self.updated_at = int(time.time())

    def unlock_htlc(self, amount: int) -> None:
        """Unlock funds from a resolved/cancelled HTLC."""
        self.pending_htlc_amount = max(0, self.pending_htlc_amount - amount)
        self.updated_at = int(time.time())

    @property
    def available_balance(self) -> int:
        """Balance available for new payments/HTLCs (excludes locked funds)."""
        return self.total_deposit - self.total_paid - self.pending_htlc_amount

    @property
    def remaining_balance(self) -> int:
        """Remaining balance available for payments."""
        return self.total_deposit - self.total_paid

    @property
    def is_token_channel(self) -> bool:
        """Whether this channel uses an ERC-20 token instead of native ETH."""
        return bool(self.token_address)

    def to_dict(self) -> dict:
        """Serialize channel state."""
        d = {
            "channel_id": self.channel_id.hex(),
            "sender": self.sender,
            "receiver": self.receiver,
            "total_deposit": self.total_deposit,
            "state": self.state.name,
            "nonce": self.nonce,
            "total_paid": self.total_paid,
            "remaining_balance": self.remaining_balance,
            "available_balance": self.available_balance,
            "pending_htlc_amount": self.pending_htlc_amount,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "peer_id": self.peer_id,
        }
        if self.close_expiration:
            d["close_initiated_at"] = self.close_initiated_at
            d["close_expiration"] = self.close_expiration
            d["closing_nonce"] = self.closing_nonce
            d["closing_amount"] = self.closing_amount
            d["challenge_expired"] = self.challenge_expired
        if self.on_chain_tx:
            d["on_chain_tx"] = self.on_chain_tx
        if self.token_address:
            d["token_address"] = self.token_address
        if self.chain_type != "ethereum":
            d["chain_type"] = self.chain_type
        if self.sla_terms:
            d["sla_terms"] = self.sla_terms
        if self.dispute_reason:
            d["dispute_reason"] = self.dispute_reason
        return d
