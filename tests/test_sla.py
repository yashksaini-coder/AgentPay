"""Tests for the SLA monitoring system."""

from __future__ import annotations

import time

from agentic_payments.negotiation.models import SLATerms
from agentic_payments.sla.monitor import SLAMonitor


def _make_terms(**kwargs) -> SLATerms:
    defaults = {
        "max_latency_ms": 200,
        "min_availability": 0.99,
        "max_error_rate": 0.05,
        "min_throughput": 10,
        "penalty_rate": 1000,
        "measurement_window": 3600,
        "dispute_threshold": 3,
    }
    defaults.update(kwargs)
    return SLATerms(**defaults)


def test_sla_terms_serialization_roundtrip():
    terms = _make_terms()
    d = terms.to_dict()
    restored = SLATerms.from_dict(d)
    assert restored.max_latency_ms == terms.max_latency_ms
    assert restored.min_availability == terms.min_availability
    assert restored.max_error_rate == terms.max_error_rate
    assert restored.min_throughput == terms.min_throughput
    assert restored.penalty_rate == terms.penalty_rate
    assert restored.measurement_window == terms.measurement_window
    assert restored.dispute_threshold == terms.dispute_threshold


def test_register_channel():
    mon = SLAMonitor()
    terms = _make_terms()
    mon.register_channel("ch-001", terms)
    status = mon.get_status("ch-001")
    assert status is not None
    assert status["channel_id"] == "ch-001"
    assert status["compliant"] is True


def test_record_request_success_no_violation():
    mon = SLAMonitor()
    mon.register_channel("ch-001", _make_terms(max_latency_ms=200, max_error_rate=0.5))
    violations = mon.record_request("ch-001", latency_ms=100.0, success=True)
    assert violations == []


def test_record_request_latency_violation():
    mon = SLAMonitor()
    mon.register_channel("ch-001", _make_terms(max_latency_ms=200))
    violations = mon.record_request("ch-001", latency_ms=300.0, success=True)
    assert len(violations) == 1
    assert violations[0].violation_type == "latency"
    assert violations[0].measured_value == 300.0
    assert violations[0].threshold_value == 200.0


def test_record_request_error_rate_violation():
    mon = SLAMonitor()
    mon.register_channel("ch-001", _make_terms(max_error_rate=0.1, max_latency_ms=0))
    # First request is an error → error_rate = 1.0 > 0.1
    violations = mon.record_request("ch-001", latency_ms=50.0, success=False)
    assert len(violations) == 1
    assert violations[0].violation_type == "error_rate"
    assert violations[0].measured_value == 1.0


def test_get_violations_returns_all():
    mon = SLAMonitor()
    mon.register_channel("ch-A", _make_terms(max_latency_ms=100))
    mon.register_channel("ch-B", _make_terms(max_latency_ms=100))
    mon.record_request("ch-A", latency_ms=200.0, success=True)
    mon.record_request("ch-B", latency_ms=300.0, success=True)
    all_violations = mon.get_violations()
    assert len(all_violations) == 2
    channel_ids = {v.channel_id for v in all_violations}
    assert channel_ids == {"ch-A", "ch-B"}


def test_get_non_compliant_channels():
    mon = SLAMonitor()
    # dispute_threshold=2 means 2 violations → non-compliant
    mon.register_channel("ch-bad", _make_terms(max_latency_ms=100, dispute_threshold=2))
    mon.register_channel("ch-good", _make_terms(max_latency_ms=100, dispute_threshold=5))
    mon.record_request("ch-bad", latency_ms=200.0, success=True)
    mon.record_request("ch-bad", latency_ms=200.0, success=True)
    mon.record_request("ch-good", latency_ms=200.0, success=True)
    non_compliant = mon.get_non_compliant_channels()
    assert "ch-bad" in non_compliant
    assert "ch-good" not in non_compliant


def test_window_reset():
    mon = SLAMonitor()
    # measurement_window=1 second so it expires quickly
    mon.register_channel(
        "ch-001", _make_terms(max_error_rate=0.1, max_latency_ms=0, measurement_window=1)
    )
    # Record an error → error_rate = 1.0
    mon.record_request("ch-001", latency_ms=50.0, success=False)
    status_before = mon.get_status("ch-001")
    assert status_before["error_rate"] == 1.0

    # Wait for the window to expire
    time.sleep(1.1)

    # After window reset, new request starts fresh → error_rate = 0.0
    mon.record_request("ch-001", latency_ms=50.0, success=True)
    status_after = mon.get_status("ch-001")
    assert status_after["error_rate"] == 0.0


def test_list_monitored():
    mon = SLAMonitor()
    mon.register_channel("ch-A", _make_terms())
    mon.register_channel("ch-B", _make_terms())
    monitored = mon.list_monitored()
    assert len(monitored) == 2
    ids = {m["channel_id"] for m in monitored}
    assert ids == {"ch-A", "ch-B"}
