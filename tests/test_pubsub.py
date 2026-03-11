"""Tests for pubsub topic definitions."""

from __future__ import annotations

from agentic_payments.pubsub.topics import (
    ALL_TOPICS,
    TOPIC_AGENT_CAPABILITIES,
    TOPIC_AGENT_DISCOVERY,
    TOPIC_PAYMENT_RECEIPTS,
)


class TestTopics:
    def test_topic_format(self):
        """All topics should follow the /agentic/... naming convention."""
        for topic in ALL_TOPICS:
            assert topic.startswith("/agentic/")
            assert topic.count("/") >= 3

    def test_all_topics_included(self):
        """ALL_TOPICS should contain all defined topics."""
        assert TOPIC_AGENT_CAPABILITIES in ALL_TOPICS
        assert TOPIC_PAYMENT_RECEIPTS in ALL_TOPICS
        assert TOPIC_AGENT_DISCOVERY in ALL_TOPICS

    def test_topics_unique(self):
        """No duplicate topics."""
        assert len(ALL_TOPICS) == len(set(ALL_TOPICS))
