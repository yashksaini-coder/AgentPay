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
from agentic_payments.protocol.messages import (
    ErrorMessage,
    MessageType,
    PaymentAck,
    from_wire,
    to_wire,
)

if TYPE_CHECKING:
    from agentic_payments.payments.manager import ChannelManager

logger = structlog.get_logger(__name__)

PROTOCOL_ID = "/agentic-payments/1.0.0"


class PaymentProtocolHandler:
    """Handles incoming payment protocol streams.

    When a remote peer opens a stream on /agentic-payments/1.0.0,
    the libp2p host dispatches to handle_stream(). Messages are
    read via length-prefix framing + msgpack, dispatched by type,
    and responses are written back on the same stream.
    """

    def __init__(self, channel_manager: ChannelManager) -> None:
        self.channel_manager = channel_manager

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
            case _:
                return MessageType.ERROR, ErrorMessage(
                    code=1, message=f"Unsupported message type: {msg_type}"
                )

    async def _handle_open(self, msg: Any, remote_peer: str) -> tuple[MessageType, Any]:
        """Handle a PaymentOpen request."""
        try:
            await self.channel_manager.handle_open_request(msg, remote_peer)
            return MessageType.PAYMENT_ACK, PaymentAck(
                channel_id=msg.channel_id,
                nonce=msg.nonce,
                status="accepted",
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
                reason="Internal error",
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
                reason="Internal error",
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
