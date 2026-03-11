"""Gossipsub publish/subscribe using py-libp2p's Pubsub + GossipSub classes.

Wraps libp2p.pubsub.pubsub.Pubsub to provide topic management,
message serialization (msgpack), and handler dispatch.
"""

from __future__ import annotations

from typing import Any, Callable, Coroutine

import msgpack
import structlog
import trio
from libp2p.peer.id import ID as PeerID
from libp2p.pubsub.pubsub import Pubsub

from agentic_payments.pubsub.topics import (
    ALL_TOPICS,
    TOPIC_AGENT_CAPABILITIES,
    TOPIC_PAYMENT_RECEIPTS,
)

logger = structlog.get_logger(__name__)

# Maximum allowed pubsub message size (bytes)
MAX_PUBSUB_MESSAGE_SIZE = 256 * 1024  # 256 KB

# Type alias for message handlers: async (data: dict, from_peer: PeerID) -> None
MessageHandler = Callable[[dict, PeerID], Coroutine[Any, Any, None]]


class PubsubBroadcaster:
    """Manages gossipsub topic subscriptions and message broadcasting.

    Uses libp2p's Pubsub.subscribe() to get ISubscriptionAPI objects,
    then iterates over incoming messages in background tasks.
    """

    def __init__(self, pubsub: Pubsub) -> None:
        self.pubsub = pubsub
        self._subscriptions: dict[str, Any] = {}  # topic -> ISubscriptionAPI
        self._handlers: dict[str, list[MessageHandler]] = {}

    async def subscribe_all(self) -> None:
        """Subscribe to all standard agentic topics."""
        for topic in ALL_TOPICS:
            await self.subscribe(topic)

    async def subscribe(self, topic: str) -> None:
        """Subscribe to a gossipsub topic via libp2p's Pubsub.subscribe()."""
        sub = await self.pubsub.subscribe(topic)
        self._subscriptions[topic] = sub
        logger.info("pubsub_subscribed", topic=topic)

    async def unsubscribe(self, topic: str) -> None:
        """Unsubscribe from a topic."""
        if topic in self._subscriptions:
            await self.pubsub.unsubscribe(topic)
            del self._subscriptions[topic]
            logger.info("pubsub_unsubscribed", topic=topic)

    async def publish(self, topic: str, data: dict) -> None:
        """Publish a msgpack-encoded message to a gossipsub topic.

        Uses libp2p's Pubsub.publish() which signs the message (strict_signing)
        and propagates it through the GossipSub mesh.
        """
        payload = msgpack.packb(data, use_bin_type=True)
        await self.pubsub.publish(topic, payload)
        logger.debug("pubsub_published", topic=topic, size=len(payload))

    def on_message(self, topic: str, handler: MessageHandler) -> None:
        """Register an async handler for messages on a topic."""
        self._handlers.setdefault(topic, []).append(handler)

    async def run(self, nursery: trio.Nursery) -> None:
        """Start background listeners for all subscribed topics.

        Each topic gets its own trio task that iterates over the
        ISubscriptionAPI's async iterator, decodes msgpack, and
        dispatches to registered handlers.
        """
        for topic, sub in self._subscriptions.items():
            nursery.start_soon(self._listen, topic, sub)

    async def _listen(self, topic: str, sub: Any) -> None:
        """Listen for messages on a single topic subscription.

        Uses the ISubscriptionAPI's async iterator:
            async for message in sub:
                message.data -> bytes
                message.from_id -> PeerID
        """
        logger.info("pubsub_listening", topic=topic)
        async for message in sub:
            try:
                if len(message.data) > MAX_PUBSUB_MESSAGE_SIZE:
                    logger.warning(
                        "pubsub_message_too_large",
                        topic=topic,
                        size=len(message.data),
                        from_peer=str(message.from_id),
                    )
                    continue
                data = msgpack.unpackb(message.data, raw=False)
                if not isinstance(data, dict):
                    logger.warning("pubsub_message_not_dict", topic=topic)
                    continue
                from_peer = message.from_id
                logger.debug(
                    "pubsub_message_received",
                    topic=topic,
                    from_peer=str(from_peer),
                )
                for handler in self._handlers.get(topic, []):
                    await handler(data, from_peer)
            except Exception:
                logger.exception("pubsub_message_error", topic=topic)

    async def broadcast_capabilities(self, capabilities: dict) -> None:
        """Publish agent capabilities advertisement on the capabilities topic."""
        await self.publish(
            TOPIC_AGENT_CAPABILITIES,
            {
                "type": "capabilities",
                "data": capabilities,
            },
        )

    async def broadcast_receipt(self, receipt: dict) -> None:
        """Publish a payment receipt on the receipts topic."""
        await self.publish(
            TOPIC_PAYMENT_RECEIPTS,
            {
                "type": "receipt",
                "data": receipt,
            },
        )
