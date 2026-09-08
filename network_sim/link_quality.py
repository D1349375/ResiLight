"""
5G MEC Network Quality Simulation Layer.

Simulates wireless/fiber link communication degradation between edge road-side units (RSUs)
and cloud coordination services.

Models:
- Latency (ms) with Gaussian/uniform jitter
- Packet loss rate [0.0, 1.0]
- Disconnection / link-cut events
- Programmable scenario event injection (e.g., fiber cut, peak congestion)
"""
import random
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("network_sim")


@dataclass(frozen=True)
class NetworkQuality:
    """Snapshot of current link metrics for a communication link or node."""
    latency_ms: float
    jitter_ms: float
    packet_loss_rate: float
    is_connected: bool = True

    @property
    def sample_latency_ms(self) -> float:
        """Returns latency with randomized jitter applied."""
        if not self.is_connected:
            return float("inf")
        jitter = random.uniform(-self.jitter_ms, self.jitter_ms)
        return max(1.0, self.latency_ms + jitter)


@dataclass
class DegradationEvent:
    """Defines a time-windowed network degradation event."""
    name: str
    start_step: int
    duration_steps: int
    latency_ms: float
    jitter_ms: float
    packet_loss_rate: float
    is_connected: bool = True
    affected_nodes: Optional[List[str]] = None  # None indicates all nodes

    @property
    def end_step(self) -> int:
        return self.start_step + self.duration_steps


class NetworkQualitySimulator:
    """
    Manages and simulates link quality across simulation steps.
    """

    def __init__(
        self,
        base_latency_ms: float = 15.0,
        base_jitter_ms: float = 2.0,
        base_loss_rate: float = 0.001,
        seed: Optional[int] = 42,
    ):
        self.base_quality = NetworkQuality(
            latency_ms=base_latency_ms,
            jitter_ms=base_jitter_ms,
            packet_loss_rate=base_loss_rate,
            is_connected=True,
        )
        self._scheduled_events: List[DegradationEvent] = []
        self._current_step = 0
        self._node_overrides: Dict[str, NetworkQuality] = {}
        self._rng = random.Random(seed)

    def inject_event(self, event: DegradationEvent) -> None:
        """Schedules a degradation event."""
        self._scheduled_events.append(event)
        logger.info(
            f"Scheduled degradation event '{event.name}' from step {event.start_step} "
            f"to {event.end_step} (latency={event.latency_ms}ms, loss={event.packet_loss_rate*100:.1f}%)"
        )

    def step(self, current_step: int) -> None:
        """Updates internal step clock."""
        self._current_step = current_step

    def get_quality(self, node_id: Optional[str] = None) -> NetworkQuality:
        """
        Returns the effective link quality for a given node at the current step.
        If multiple events are active, the most severe condition applies.
        """
        # Filter active events at current step
        active_events = [
            ev for ev in self._scheduled_events
            if ev.start_step <= self._current_step < ev.end_step
            and (ev.affected_nodes is None or (node_id is not None and node_id in ev.affected_nodes))
        ]

        if not active_events:
            return self.base_quality

        # Take worst-case combination of active events
        is_connected = all(ev.is_connected for ev in active_events)
        if not is_connected:
            return NetworkQuality(
                latency_ms=9999.0,
                jitter_ms=0.0,
                packet_loss_rate=1.0,
                is_connected=False,
            )

        worst_latency = max(ev.latency_ms for ev in active_events)
        worst_jitter = max(ev.jitter_ms for ev in active_events)
        worst_loss = max(ev.packet_loss_rate for ev in active_events)

        return NetworkQuality(
            latency_ms=max(worst_latency, self.base_quality.latency_ms),
            jitter_ms=max(worst_jitter, self.base_quality.jitter_ms),
            packet_loss_rate=max(worst_loss, self.base_quality.packet_loss_rate),
            is_connected=True,
        )

    def can_deliver_packet(self, node_id: Optional[str] = None) -> bool:
        """
        Determines probabilistically whether a packet successfully transmits
        under current link quality conditions.
        """
        quality = self.get_quality(node_id)
        if not quality.is_connected:
            return False

        if quality.packet_loss_rate >= 1.0:
            return False

        if quality.packet_loss_rate <= 0.0:
            return True

        return self._rng.random() >= quality.packet_loss_rate

    def get_effective_delay_steps(self, node_id: Optional[str] = None, step_length_s: float = 1.0) -> int:
        """
        Calculates how many simulation steps a message is delayed.
        """
        quality = self.get_quality(node_id)
        if not quality.is_connected:
            return 999999

        sample_ms = quality.sample_latency_ms
        delay_s = sample_ms / 1000.0
        steps = int(round(delay_s / step_length_s))
        return max(0, steps)
