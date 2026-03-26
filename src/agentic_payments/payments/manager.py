"""Channel manager: tracks payment channels per peer."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import structlog
import trio

from agentic_payments.payments.channel import ChannelError, ChannelState, PaymentChannel
from agentic_payments.payments.voucher import SignedVoucher
from agentic_payments.protocol.errors import PaymentError, PaymentErrorCode
from agentic_payments.protocol.messages import PaymentClose, PaymentOpen, PaymentUpdate

if TYPE_CHECKING:
    from agentic_payments.policies.engine import PolicyEngine

logger = structlog.get_logger(__name__)

# Maximum allowed clock skew for voucher timestamps (seconds)
MAX_TIMESTAMP_SKEW = 300


class ChannelManager:
    """Manages all payment channels for this node."""

    def __init__(self, local_address: str, policy_engine: PolicyEngine | None = None) -> None:
        self.local_address = local_address
        self.channels: dict[bytes, PaymentChannel] = {}
        self._channel_locks: dict[bytes, trio.Lock] = {}
        self.policy_engine = policy_engine

    def get_channel(self, channel_id: bytes) -> PaymentChannel:
        """Get a channel by ID."""
        channel = self.channels.get(channel_id)
        if channel is None:
            raise KeyError(f"Channel not found: {channel_id.hex()[:16]}")
        return channel

    def _get_channel_lock(self, channel_id: bytes) -> trio.Lock:
        """Get or create a per-channel lock for serializing payments."""
        lock = self._channel_locks.get(channel_id)
        if lock is None:
            lock = trio.Lock()
            self._channel_locks[channel_id] = lock
        return lock

    def list_channels(self, state: ChannelState | None = None) -> list[PaymentChannel]:
        """List channels, optionally filtered by state."""
        channels = list(self.channels.values())
        if state is not None:
            channels = [c for c in channels if c.state == state]
        return channels

    def create_channel(
        self,
        channel_id: bytes,
        receiver: str,
        total_deposit: int,
        peer_id: str,
    ) -> PaymentChannel:
        """Create a new outbound payment channel."""
        channel = PaymentChannel(
            channel_id=channel_id,
            sender=self.local_address,
            receiver=receiver,
            total_deposit=total_deposit,
            peer_id=peer_id,
        )
        self.channels[channel_id] = channel
        logger.info(
            "channel_created",
            channel_id=channel_id.hex()[:16],
            receiver=receiver,
            deposit=total_deposit,
        )
        return channel

    def remove_channel(self, channel_id: bytes) -> None:
        """Remove a channel from the registry (cleanup on failure)."""
        self.channels.pop(channel_id, None)

    async def handle_open_request(self, msg: PaymentOpen, peer_id: str) -> PaymentChannel:
        """Handle an incoming channel open request from a peer."""
        if msg.channel_id in self.channels:
            raise PaymentError(PaymentErrorCode.CHANNEL_ALREADY_EXISTS, detail=f"Channel {msg.channel_id.hex()[:16]} already exists")

        if msg.total_deposit <= 0:
            raise PaymentError(PaymentErrorCode.CHANNEL_DEPOSIT_INVALID, detail="Deposit must be positive")

        channel = PaymentChannel(
            channel_id=msg.channel_id,
            sender=msg.sender,
            receiver=self.local_address,
            total_deposit=msg.total_deposit,
            peer_id=peer_id,
        )
        channel.accept()
        channel.activate()
        self.channels[msg.channel_id] = channel
        logger.info(
            "channel_accepted",
            channel_id=msg.channel_id.hex()[:16],
            sender=msg.sender,
            deposit=msg.total_deposit,
        )
        return channel

    async def handle_payment_update(self, msg: PaymentUpdate) -> None:
        """Handle an incoming payment update (voucher)."""
        channel = self.get_channel(msg.channel_id)

        # Validate timestamp is recent to prevent replay of old vouchers
        now = int(time.time())
        if abs(msg.timestamp - now) > MAX_TIMESTAMP_SKEW:
            raise PaymentError(PaymentErrorCode.EXPIRED_PAYMENT, detail=f"Voucher timestamp too skewed: {msg.timestamp} vs now {now}")

        voucher = SignedVoucher(
            channel_id=msg.channel_id,
            nonce=msg.nonce,
            amount=msg.amount,
            timestamp=msg.timestamp,
            signature=msg.signature,
            task_id=msg.task_id,
        )

        # Verify the voucher signature matches the channel sender
        if not voucher.verify(channel.sender):
            raise PaymentError(PaymentErrorCode.INVALID_SIGNATURE, detail="Voucher signature does not match channel sender")

        channel.apply_voucher(voucher)

    async def handle_close_request(self, msg: PaymentClose) -> None:
        """Handle an incoming channel close request.

        Validates that the close message matches the channel's current state.
        """
        channel = self.get_channel(msg.channel_id)

        if channel.state != ChannelState.ACTIVE:
            raise PaymentError(
                PaymentErrorCode.CHANNEL_CLOSE_MISMATCH,
                detail=f"Cannot close channel in state {channel.state.name}",
            )

        # Verify close parameters match our known state
        if msg.final_nonce != channel.nonce:
            raise PaymentError(
                PaymentErrorCode.CHANNEL_CLOSE_MISMATCH,
                detail=f"Close nonce mismatch: got {msg.final_nonce}, expected {channel.nonce}",
            )
        if msg.final_amount != channel.total_paid:
            raise PaymentError(
                PaymentErrorCode.CHANNEL_CLOSE_MISMATCH,
                detail=f"Close amount mismatch: got {msg.final_amount}, expected {channel.total_paid}",
            )

        if msg.cooperative:
            channel.cooperative_close()
        else:
            channel.request_close()
        logger.info(
            "channel_close_requested",
            channel_id=msg.channel_id.hex()[:16],
            cooperative=msg.cooperative,
            final_amount=msg.final_amount,
        )

    async def send_payment(
        self,
        channel_id: bytes,
        amount: int,
        private_key: str,
        send_fn: Any,
        task_id: str = "",
    ) -> SignedVoucher:
        """Create and send a payment voucher on a channel.

        Sends the voucher to the peer FIRST, then applies locally only on success.
        This prevents the channel from becoming wedged if the network send fails.
        Uses per-channel lock to prevent nonce races from concurrent payments.
        """
        if amount <= 0:
            raise ValueError("Payment amount must be positive")

        lock = self._get_channel_lock(channel_id)
        async with lock:
            channel = self.get_channel(channel_id)

            if channel.sender != self.local_address:
                raise ValueError(
                    "Only the channel sender can send payments. "
                    f"This node ({self.local_address[:10]}...) is the receiver, "
                    f"not the sender ({channel.sender[:10]}...)."
                )
            new_nonce = channel.nonce + 1
            new_total = channel.total_paid + amount

            if amount > channel.available_balance:
                raise ChannelError(
                    f"Payment {amount} exceeds available balance {channel.available_balance} "
                    f"(deposit={channel.total_deposit}, paid={channel.total_paid}, "
                    f"htlc_locked={channel.pending_htlc_amount})"
                )

            # Policy check before creating voucher
            if self.policy_engine is not None:
                self.policy_engine.check_payment(amount, channel.peer_id)

            voucher = SignedVoucher.create(
                channel_id=channel_id,
                nonce=new_nonce,
                amount=new_total,
                private_key=private_key,
                task_id=task_id,
            )

            # Send first — if this fails, channel state is unchanged
            await send_fn(
                PaymentUpdate(
                    channel_id=channel_id,
                    nonce=voucher.nonce,
                    amount=voucher.amount,
                    timestamp=voucher.timestamp,
                    signature=voucher.signature,
                    task_id=task_id,
                )
            )

            # Commit locally only after successful send
            channel.apply_voucher(voucher)

            # Record payment for policy tracking
            if self.policy_engine is not None:
                self.policy_engine.record_payment(amount)

            return voucher
