"""Channel manager: tracks payment channels per peer."""

from __future__ import annotations

import time
from typing import Any

import structlog

from agentic_payments.payments.channel import ChannelState, PaymentChannel
from agentic_payments.payments.voucher import SignedVoucher
from agentic_payments.protocol.messages import PaymentClose, PaymentOpen, PaymentUpdate

logger = structlog.get_logger(__name__)

# Maximum allowed clock skew for voucher timestamps (seconds)
MAX_TIMESTAMP_SKEW = 300


class ChannelManager:
    """Manages all payment channels for this node."""

    def __init__(self, local_address: str) -> None:
        self.local_address = local_address
        self.channels: dict[bytes, PaymentChannel] = {}

    def get_channel(self, channel_id: bytes) -> PaymentChannel:
        """Get a channel by ID."""
        channel = self.channels.get(channel_id)
        if channel is None:
            raise KeyError(f"Channel not found: {channel_id.hex()[:16]}")
        return channel

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
            raise ValueError("Channel ID already exists")

        if msg.total_deposit <= 0:
            raise ValueError("Deposit must be positive")

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
            raise ValueError(f"Voucher timestamp too skewed: {msg.timestamp} vs now {now}")

        voucher = SignedVoucher(
            channel_id=msg.channel_id,
            nonce=msg.nonce,
            amount=msg.amount,
            timestamp=msg.timestamp,
            signature=msg.signature,
        )

        # Verify the voucher signature matches the channel sender
        if not voucher.verify(channel.sender):
            raise ValueError("Invalid voucher signature")

        channel.apply_voucher(voucher)

    async def handle_close_request(self, msg: PaymentClose) -> None:
        """Handle an incoming channel close request.

        Validates that the close message matches the channel's current state.
        """
        channel = self.get_channel(msg.channel_id)

        # Verify close parameters match our known state
        if msg.final_nonce != channel.nonce:
            raise ValueError(
                f"Close nonce mismatch: got {msg.final_nonce}, expected {channel.nonce}"
            )
        if msg.final_amount != channel.total_paid:
            raise ValueError(
                f"Close amount mismatch: got {msg.final_amount}, expected {channel.total_paid}"
            )

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
    ) -> SignedVoucher:
        """Create and send a payment voucher on a channel.

        Sends the voucher to the peer FIRST, then applies locally only on success.
        This prevents the channel from becoming wedged if the network send fails.
        """
        if amount <= 0:
            raise ValueError("Payment amount must be positive")

        channel = self.get_channel(channel_id)

        if channel.sender != self.local_address:
            raise ValueError(
                "Only the channel sender can send payments. "
                f"This node ({self.local_address[:10]}...) is the receiver, "
                f"not the sender ({channel.sender[:10]}...)."
            )
        new_nonce = channel.nonce + 1
        new_total = channel.total_paid + amount

        voucher = SignedVoucher.create(
            channel_id=channel_id,
            nonce=new_nonce,
            amount=new_total,
            private_key=private_key,
        )

        # Send first — if this fails, channel state is unchanged
        await send_fn(
            PaymentUpdate(
                channel_id=channel_id,
                nonce=voucher.nonce,
                amount=voucher.amount,
                timestamp=voucher.timestamp,
                signature=voucher.signature,
            )
        )

        # Commit locally only after successful send
        channel.apply_voucher(voucher)

        return voucher
