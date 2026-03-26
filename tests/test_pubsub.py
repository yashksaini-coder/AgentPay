"""Tests for pubsub topic definitions and GossipSub scoring."""

from __future__ import annotations

from libp2p.pubsub.score import ScoreParams, TopicScoreParams

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


class TestGossipSubScoring:
    def test_score_params_construction(self):
        """ScoreParams should accept our custom weights."""
        params = ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=0.5, cap=3600.0, decay=0.9997),
            p2_first_message_deliveries=TopicScoreParams(weight=1.0, cap=100.0, decay=0.999),
            p4_invalid_messages=TopicScoreParams(weight=-10.0, cap=0.0, decay=0.99),
            graylist_threshold=-400.0,
        )
        assert params.graylist_threshold == -400.0
        assert params.p1_time_in_mesh.weight == 0.5
        assert params.p4_invalid_messages.weight == -10.0

    def test_app_specific_score_fn(self):
        """App-specific scoring should accept a callable."""
        from libp2p.peer.id import ID as PeerID

        def score_fn(peer_id: PeerID) -> float:
            return 42.0

        params = ScoreParams(
            app_specific_score_fn=score_fn,
            p6_appl_slack_weight=10.0,
        )
        assert params.app_specific_score_fn is not None
        assert params.p6_appl_slack_weight == 10.0

    def test_graylist_threshold_negative(self):
        """Graylist threshold should be negative (lower = stricter)."""
        params = ScoreParams(graylist_threshold=-400.0)
        assert params.graylist_threshold < 0

    def test_reputation_to_app_score_mapping(self):
        """Reputation trust score should map correctly to app score range."""
        from agentic_payments.reputation.tracker import ReputationTracker

        tracker = ReputationTracker()
        # Unknown peer → 0.5 (neutral)
        trust = tracker.get_trust_score("unknown_peer")
        app_score = (trust - 0.5) * 200
        assert app_score == 0.0  # neutral

        # Record some positive interactions
        tracker.record_payment_sent("good_peer", 1000, 0.5)
        trust = tracker.get_trust_score("good_peer")
        app_score = (trust - 0.5) * 200
        # Should be > 0 for a good peer
        assert app_score != 0.0
