"""Stream handler for the payment protocol over libp2p.

Registered via host.set_stream_handler(TProtocol(PROTOCOL_ID), handler).
Each incoming stream is a bidirectional byte pipe multiplexed over Yamux.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from libp2p.network.stream.net_stream import NetStream

from agentic_payments.payments.channel import ChannelError
from agentic_payments.protocol.codec import read_message, write_message
from agentic_payments.protocol.errors import PaymentError, PaymentErrorCode
from agentic_payments.protocol.messages import (
    ErrorMessage,
    MessageType,
    PaymentAck,
    from_wire,
    to_wire,
)

if TYPE_CHECKING:
    from agentic_payments.payments.manager import ChannelManager
    from agentic_payments.routing.htlc import HtlcManager

logger = structlog.get_logger(__name__)

PROTOCOL_ID = "/agentic-payments/1.0.0"


class PaymentProtocolHandler:
    """Handles incoming payment protocol streams.

    When a remote peer opens a stream on /agentic-payments/1.0.0,
    the libp2p host dispatches to handle_stream(). Messages are
    read via length-prefix framing + msgpack, dispatched by type,
    and responses are written back on the same stream.
    """

    def __init__(
        self,
        channel_manager: ChannelManager,
        htlc_manager: HtlcManager | None = None,
        on_htlc_propose: Any = None,
        on_htlc_fulfill: Any = None,
        on_htlc_cancel: Any = None,
        on_channel_opened: Any = None,
        on_negotiate_propose: Any = None,
        on_negotiate_counter: Any = None,
        on_negotiate_accept: Any = None,
        on_negotiate_reject: Any = None,
    ) -> None:
        self.channel_manager = channel_manager
        self.htlc_manager = htlc_manager
        # Callbacks for HTLC events (set by AgentNode for forwarding logic)
        self._on_htlc_propose = on_htlc_propose
        self._on_htlc_fulfill = on_htlc_fulfill
        self._on_htlc_cancel = on_htlc_cancel
        # Callback when a channel is accepted (receiver side)
        self._on_channel_opened = on_channel_opened
        # Callbacks for negotiation events
        self._on_negotiate_propose = on_negotiate_propose
        self._on_negotiate_counter = on_negotiate_counter
        self._on_negotiate_accept = on_negotiate_accept
        self._on_negotiate_reject = on_negotiate_reject

    async def handle_stream(self, stream: NetStream) -> None:
        """Handle an incoming libp2p stream for the payment protocol.

        Reads messages in a loop until the stream is closed or reset.
        Each message gets a typed response written back.
        A single malformed message is logged and skipped, not fatal.
        """
        remote_peer = "unknown"
        if hasattr(stream, "muxed_conn") and hasattr(stream.muxed_conn, "peer_id"):
            remote_peer = str(stream.muxed_conn.peer_id)

        logger.info("payment_stream_opened", remote_peer=remote_peer)

        try:
            while True:
                try:
                    raw = await read_message(stream)
                except ConnectionError:
                    logger.info("payment_stream_closed", remote_peer=remote_peer)
                    break

                try:
                    msg_type, msg = from_wire(raw)
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning(
                        "malformed_message",
                        error=str(e),
                        remote_peer=remote_peer,
                    )
                    continue  # skip bad message, don't kill the stream

                logger.debug(
                    "message_received",
                    type=msg_type.name,
                    remote_peer=remote_peer,
                )

                response = await self._dispatch(msg_type, msg, remote_peer)
                if response is not None:
                    resp_type, resp_msg = response
                    await write_message(stream, to_wire(resp_type, resp_msg))
        except Exception:
            logger.exception("payment_stream_error", remote_peer=remote_peer)
        finally:
            try:
                await stream.close()
            except Exception:
                logger.debug("stream_close_error", remote_peer=remote_peer, exc_info=True)

    async def _dispatch(
        self, msg_type: MessageType, msg: Any, remote_peer: str
    ) -> tuple[MessageType, Any] | None:
        """Dispatch a message to the appropriate handler by type."""
        match msg_type:
            case MessageType.PAYMENT_OPEN:
                return await self._handle_open(msg, remote_peer)
            case MessageType.PAYMENT_UPDATE:
                return await self._handle_update(msg, remote_peer)
            case MessageType.PAYMENT_CLOSE:
                return await self._handle_close(msg, remote_peer)
            case MessageType.PAYMENT_ACK:
                return None  # ACKs are terminal
            case MessageType.HTLC_PROPOSE:
                return await self._handle_htlc_propose(msg, remote_peer)
            case MessageType.HTLC_FULFILL:
                return await self._handle_htlc_fulfill(msg, remote_peer)
            case MessageType.HTLC_CANCEL:
                return await self._handle_htlc_cancel(msg, remote_peer)
            case MessageType.NEGOTIATE_PROPOSE:
                return await self._handle_negotiate(self._on_negotiate_propose, msg, remote_peer)
            case MessageType.NEGOTIATE_COUNTER:
                return await self._handle_negotiate(self._on_negotiate_counter, msg, remote_peer)
            case MessageType.NEGOTIATE_ACCEPT:
                return await self._handle_negotiate(self._on_negotiate_accept, msg, remote_peer)
            case MessageType.NEGOTIATE_REJECT:
                return await self._handle_negotiate(self._on_negotiate_reject, msg, remote_peer)
            case _:
                return MessageType.ERROR, ErrorMessage(
                    code=int(PaymentErrorCode.UNSUPPORTED_MESSAGE),
                    message=f"[{PaymentErrorCode.UNSUPPORTED_MESSAGE.name}] Unsupported message type: {msg_type}",
                )

    async def _handle_open(self, msg: Any, remote_peer: str) -> tuple[MessageType, Any]:
        """Handle a PaymentOpen request."""
        try:
            channel = await self.channel_manager.handle_open_request(msg, remote_peer)
            # Notify AgentNode so it can announce the channel for routing
            if self._on_channel_opened is not None:
                try:
                    await self._on_channel_opened(channel)
                except Exception:
                    logger.warning("channel_opened_callback_error", exc_info=True)
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=msg.channel_id,
                nonce=msg.nonce,
                status="accepted",
            )
        except PaymentError as e:
            logger.warning(
                "open_rejected", error_code=e.code.name, error=str(e), remote_peer=remote_peer
            )
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=msg.channel_id,
                nonce=msg.nonce,
                status="rejected",
                reason=f"[{e.code.name}] {e.detail}",
            )
        except (ValueError, KeyError, ChannelError) as e:
            logger.warning("open_rejected", error=str(e), remote_peer=remote_peer)
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=msg.channel_id,
                nonce=msg.nonce,
                status="rejected",
                reason=str(e),
            )
        except Exception:
            logger.exception("open_handler_bug", remote_peer=remote_peer)
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=msg.channel_id,
                nonce=msg.nonce,
                status="rejected",
                reason=f"[{PaymentErrorCode.INTERNAL_ERROR.name}] Internal error",
            )

    async def _handle_update(self, msg: Any, remote_peer: str) -> tuple[MessageType, Any]:
        """Handle a PaymentUpdate (voucher)."""
        try:
            await self.channel_manager.handle_payment_update(msg)
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=msg.channel_id,
                nonce=msg.nonce,
                status="accepted",
            )
        except PaymentError as e:
            logger.warning(
                "update_rejected", error_code=e.code.name, error=str(e), remote_peer=remote_peer
            )
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=msg.channel_id,
                nonce=msg.nonce,
                status="rejected",
                reason=f"[{e.code.name}] {e.detail}",
            )
        except (ValueError, KeyError, ChannelError) as e:
            logger.warning("update_rejected", error=str(e), remote_peer=remote_peer)
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=msg.channel_id,
                nonce=msg.nonce,
                status="rejected",
                reason=str(e),
            )
        except Exception:
            logger.exception("update_handler_bug", remote_peer=remote_peer)
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=msg.channel_id,
                nonce=msg.nonce,
                status="rejected",
                reason=f"[{PaymentErrorCode.INTERNAL_ERROR.name}] Internal error",
            )

    async def _handle_close(self, msg: Any, remote_peer: str) -> tuple[MessageType, Any]:
        """Handle a PaymentClose request."""
        try:
            await self.channel_manager.handle_close_request(msg)
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=msg.channel_id,
                nonce=msg.final_nonce,
                status="accepted",
            )
        except (ValueError, KeyError, ChannelError) as e:
            logger.warning("close_rejected", error=str(e), remote_peer=remote_peer)
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=msg.channel_id,
                nonce=msg.final_nonce,
                status="rejected",
                reason=str(e),
            )
        except Exception:
            logger.exception("close_handler_bug", remote_peer=remote_peer)
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=msg.channel_id,
                nonce=msg.final_nonce,
                status="rejected",
                reason="Internal error",
            )

    async def _handle_htlc_propose(
        self, msg: Any, remote_peer: str
    ) -> tuple[MessageType, Any] | None:
        """Handle an incoming HTLC proposal (multi-hop forwarding)."""
        if self._on_htlc_propose is None:
            return MessageType.ERROR, ErrorMessage(code=2, message="HTLC routing not supported")
        try:
            return await self._on_htlc_propose(msg, remote_peer)
        except Exception:
            logger.exception("htlc_propose_error", remote_peer=remote_peer)
            from agentic_payments.protocol.messages import HtlcCancel

            return MessageType.HTLC_CANCEL, HtlcCancel(
                channel_id=msg.channel_id,
                htlc_id=msg.htlc_id,
                reason="Internal error processing HTLC",
            )

    async def _handle_htlc_fulfill(
        self, msg: Any, remote_peer: str
    ) -> tuple[MessageType, Any] | None:
        """Handle an HTLC fulfill (preimage revealed by downstream)."""
        if self._on_htlc_fulfill is None:
            return None
        try:
            return await self._on_htlc_fulfill(msg, remote_peer)
        except Exception:
            logger.exception("htlc_fulfill_error", remote_peer=remote_peer)
            return None

    async def _handle_htlc_cancel(
        self, msg: Any, remote_peer: str
    ) -> tuple[MessageType, Any] | None:
        """Handle an HTLC cancellation from downstream."""
        if self._on_htlc_cancel is None:
            return None
        try:
            return await self._on_htlc_cancel(msg, remote_peer)
        except Exception:
            logger.exception("htlc_cancel_error", remote_peer=remote_peer)
            return None

    async def _handle_negotiate(
        self, callback: Any, msg: Any, remote_peer: str
    ) -> tuple[MessageType, Any] | None:
        """Handle a negotiation message via callback."""
        if callback is None:
            return MessageType.ERROR, ErrorMessage(code=3, message="Negotiation not supported")
        try:
            return await callback(msg, remote_peer)
        except Exception:
            logger.exception("negotiate_handler_error", remote_peer=remote_peer)
            return MessageType.ERROR, ErrorMessage(code=4, message="Negotiation handler error")
