"""SLA compliance monitor: tracks per-channel SLA adherence."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

from agentic_payments.negotiation.models import SLATerms

logger = structlog.get_logger(__name__)


@dataclass
class SLAViolation:
    """A recorded SLA violation."""

    channel_id: str
    violation_type: str  # latency, availability, error_rate, throughput
    measured_value: float
    threshold_value: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "violation_type": self.violation_type,
            "measured_value": self.measured_value,
            "threshold_value": self.threshold_value,
            "timestamp": self.timestamp,
        }


@dataclass
class ChannelSLAState:
    """Tracking state for a channel's SLA compliance."""

    channel_id: str
    sla_terms: SLATerms
    latencies: list[float] = field(default_factory=list)
    errors: int = 0
    successes: int = 0
    window_start: float = field(default_factory=time.time)
    violations: list[SLAViolation] = field(default_factory=list)

    @property
    def total_requests(self) -> int:
        return self.errors + self.successes

    @property
    def error_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.errors / self.total_requests

    @property
    def avg_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)

    @property
    def violation_count(self) -> int:
        return len(self.violations)

    @property
    def compliant(self) -> bool:
        return self.violation_count < self.sla_terms.dispute_threshold

    def to_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "sla_terms": self.sla_terms.to_dict(),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "error_rate": round(self.error_rate, 4),
            "total_requests": self.total_requests,
            "violation_count": self.violation_count,
            "compliant": self.compliant,
            "violations": [v.to_dict() for v in self.violations[-10:]],
        }


class SLAMonitor:
    """Monitors SLA compliance across channels."""

    def __init__(self) -> None:
        self._channels: dict[str, ChannelSLAState] = {}

    def register_channel(self, channel_id: str, sla_terms: SLATerms) -> None:
        """Start monitoring a channel's SLA compliance."""
        self._channels[channel_id] = ChannelSLAState(
            channel_id=channel_id, sla_terms=sla_terms,
        )
        logger.info("sla_monitoring_started", channel=channel_id[:12])

    def record_request(
        self, channel_id: str, latency_ms: float, success: bool,
    ) -> list[SLAViolation]:
        """Record a request outcome and check for SLA violations."""
        state = self._channels.get(channel_id)
        if state is None:
            return []

        # Reset window if expired
        now = time.time()
        if now - state.window_start > state.sla_terms.measurement_window:
            state.latencies.clear()
            state.errors = 0
            state.successes = 0
            state.window_start = now

        state.latencies.append(latency_ms)
        if success:
            state.successes += 1
        else:
            state.errors += 1

        # Check violations
        new_violations: list[SLAViolation] = []

        sla = state.sla_terms
        if sla.max_latency_ms > 0 and latency_ms > sla.max_latency_ms:
            v = SLAViolation(
                channel_id=channel_id,
                violation_type="latency",
                measured_value=latency_ms,
                threshold_value=float(sla.max_latency_ms),
            )
            state.violations.append(v)
            new_violations.append(v)

        if sla.max_error_rate < 1.0 and state.error_rate > sla.max_error_rate:
            v = SLAViolation(
                channel_id=channel_id,
                violation_type="error_rate",
                measured_value=state.error_rate,
                threshold_value=sla.max_error_rate,
            )
            state.violations.append(v)
            new_violations.append(v)

        for v in new_violations:
            logger.warning(
                "sla_violation",
                channel=channel_id[:12],
                type=v.violation_type,
                measured=v.measured_value,
                threshold=v.threshold_value,
            )

        return new_violations

    def get_status(self, channel_id: str) -> dict | None:
        """Get SLA compliance status for a channel."""
        state = self._channels.get(channel_id)
        if state is None:
            return None
        return state.to_dict()

    def get_violations(self) -> list[SLAViolation]:
        """Get all violations across all monitored channels."""
        violations: list[SLAViolation] = []
        for state in self._channels.values():
            violations.extend(state.violations)
        violations.sort(key=lambda v: v.timestamp, reverse=True)
        return violations

    def get_non_compliant_channels(self) -> list[str]:
        """Get channel IDs that have exceeded violation threshold."""
        return [
            cid for cid, state in self._channels.items()
            if not state.compliant
        ]

    def list_monitored(self) -> list[dict]:
        """List all monitored channels with their SLA status."""
        return [state.to_dict() for state in self._channels.values()]
