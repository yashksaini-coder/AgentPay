"""Gossipsub topic definitions for agent coordination."""

# Agent capability advertisements (services offered, pricing)
TOPIC_AGENT_CAPABILITIES = "/agentic/capabilities/1.0.0"

# Payment receipts broadcast for transparency/auditing
TOPIC_PAYMENT_RECEIPTS = "/agentic/receipts/1.0.0"

# Agent discovery announcements
TOPIC_AGENT_DISCOVERY = "/agentic/discovery/1.0.0"

# Channel announcements for network topology (routing)
TOPIC_CHANNEL_ANNOUNCEMENTS = "/agentic/channels/1.0.0"

ALL_TOPICS = [
    TOPIC_AGENT_CAPABILITIES,
    TOPIC_PAYMENT_RECEIPTS,
    TOPIC_AGENT_DISCOVERY,
    TOPIC_CHANNEL_ANNOUNCEMENTS,
]
