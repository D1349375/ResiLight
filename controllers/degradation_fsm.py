"""
Three-Level Degradation State Machine (ResiLight Core FSM).

ARCHITECTURAL SPECIFICATION:
----------------------------
Dynamically routes traffic signal decision-making based on real-time 5G link QoS:

- Level 0 (NORMAL):
    Centralized / Cloud-coordinated multi-intersection optimization.
    Condition: latency < 50ms, jitter < 10ms, packet_loss < 1%

- Level 1 (PARTIAL):
    Neighbor-to-Neighbor (P2P) localized edge coordination.
    Condition: latency < 200ms, packet_loss < 10%

- Level 2 (FALLBACK):
    Fully decentralized Max Pressure rule engine (Varaiya, 2013).
    Condition: link failure, timeout, or packet_loss >= 10%

LOGGING & AUDIT TRAIL:
----------------------
Every state transition records an event log (JSON-serializable) containing:
{timestamp, from_level, to_level, latency_ms, jitter_ms, packet_loss_rate, reason}
This audit trail is read by the LLM Diagnostic Agent in Phase 4.
"""
import os
import json
import logging
from enum import IntEnum
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any

from network_sim.link_quality import NetworkQuality
from .max_pressure import MaxPressureController
from .fixed_time import FixedTimeController

logger = logging.getLogger("degradation_fsm")


class DegradationLevel(IntEnum):
    LEVEL_0_NORMAL = 0     # Cloud / Central Coordination
    LEVEL_1_PARTIAL = 1    # Edge P2P Local Coordination
    LEVEL_2_FALLBACK = 2   # Autonomous Max Pressure Rule Engine


@dataclass
class TransitionRecord:
    """Record of a degradation state machine transition."""
    timestamp_s: float
    from_level: int
    to_level: int
    reason: str
    latency_ms: float
    jitter_ms: float
    packet_loss_rate: float
    active_vehicles: int = 0
    total_queued: int = 0


class DegradationFSM:
    """
    State machine evaluating 5G link health and executing hierarchical degradation.
    """

    def __init__(
        self,
        tls_id: str,
        max_pressure_controller: Optional[MaxPressureController] = None,
        level0_controller: Optional[Any] = None,
        level1_controller: Optional[Any] = None,
        # Thresholds
        l0_max_latency_ms: float = 50.0,
        l0_max_jitter_ms: float = 10.0,
        l0_max_loss_rate: float = 0.01,
        l1_max_latency_ms: float = 200.0,
        l1_max_loss_rate: float = 0.10,
        debounce_steps: int = 2,
    ):
        self.tls_id = tls_id
        self.l0_max_latency = l0_max_latency_ms
        self.l0_max_jitter = l0_max_jitter_ms
        self.l0_max_loss = l0_max_loss_rate
        self.l1_max_latency = l1_max_latency_ms
        self.l1_max_loss = l1_max_loss_rate
        self.debounce_steps = debounce_steps

        # Controllers for each level
        self.max_pressure = max_pressure_controller or MaxPressureController(tls_id)
        # Default Level 0 to FixedTimeController or custom coordinator
        self.level0_controller = level0_controller or FixedTimeController(
            tls_id,
            phase_cycle=[(0, 35.0), (1, 3.0), (2, 25.0), (3, 3.0)]
        )
        self.level1_controller = level1_controller

        self.current_level = DegradationLevel.LEVEL_0_NORMAL
        self._target_level = DegradationLevel.LEVEL_0_NORMAL
        self._consecutive_target_count = 0
        self.transition_log: List[TransitionRecord] = []

    def evaluate_quality(self, quality: NetworkQuality) -> Tuple[DegradationLevel, str]:
        """
        Maps a NetworkQuality snapshot to the appropriate degradation level.
        """
        if not quality.is_connected:
            return DegradationLevel.LEVEL_2_FALLBACK, "Connection lost / fiber cut"

        if quality.packet_loss_rate >= self.l1_max_loss:
            return (
                DegradationLevel.LEVEL_2_FALLBACK,
                f"Severe packet loss ({quality.packet_loss_rate*100:.1f}% >= {self.l1_max_loss*100:.1f}%)"
            )

        if quality.latency_ms >= self.l1_max_latency:
            return (
                DegradationLevel.LEVEL_2_FALLBACK,
                f"Severe latency ({quality.latency_ms:.1f}ms >= {self.l1_max_latency:.1f}ms)"
            )

        if (
            quality.latency_ms > self.l0_max_latency
            or quality.jitter_ms > self.l0_max_jitter
            or quality.packet_loss_rate > self.l0_max_loss
        ):
            return (
                DegradationLevel.LEVEL_1_PARTIAL,
                f"Moderate degradation (lat={quality.latency_ms:.1f}ms, loss={quality.packet_loss_rate*100:.1f}%)"
            )

        return DegradationLevel.LEVEL_0_NORMAL, "Nominal 5G URLLC performance"

    def update_level(
        self,
        quality: NetworkQuality,
        current_time_s: float,
        active_vehicles: int = 0,
        total_queued: int = 0,
    ) -> DegradationLevel:
        """
        Updates the FSM with debouncing against noise.
        Records transition events into audit log.
        """
        desired_level, reason = self.evaluate_quality(quality)

        if desired_level == self._target_level:
            self._consecutive_target_count += 1
        else:
            self._target_level = desired_level
            self._consecutive_target_count = 1

        # Check debounce threshold (fast drop to Level 2 on complete disconnect; debounced for others)
        is_immediate = (desired_level == DegradationLevel.LEVEL_2_FALLBACK and not quality.is_connected)
        if is_immediate or self._consecutive_target_count >= self.debounce_steps:
            if self.current_level != desired_level:
                record = TransitionRecord(
                    timestamp_s=current_time_s,
                    from_level=int(self.current_level),
                    to_level=int(desired_level),
                    reason=reason,
                    latency_ms=quality.latency_ms,
                    jitter_ms=quality.jitter_ms,
                    packet_loss_rate=quality.packet_loss_rate,
                    active_vehicles=active_vehicles,
                    total_queued=total_queued,
                )
                self.transition_log.append(record)
                logger.warning(
                    f"[{current_time_s:.1f}s] Degradation FSM transition: Level {self.current_level.name} "
                    f"-> Level {desired_level.name} | Reason: {reason}"
                )
                self.current_level = desired_level

        return self.current_level

    def step(
        self,
        quality: NetworkQuality,
        current_time_s: float,
        lane_queues: Dict[str, int],
        lane_vehicles: Optional[Dict[str, int]] = None,
        active_vehicles: int = 0,
        total_queued: int = 0,
        delta_t: float = 1.0,
    ) -> Tuple[int, DegradationLevel]:
        """
        Advances FSM, updates degradation level, and executes corresponding controller.
        Returns (commanded_phase_index, current_degradation_level).
        """
        level = self.update_level(
            quality=quality,
            current_time_s=current_time_s,
            active_vehicles=active_vehicles,
            total_queued=total_queued,
        )

        if level == DegradationLevel.LEVEL_2_FALLBACK:
            # Level 2: Max Pressure Rule Engine (Decentralized)
            phase = self.max_pressure.step(lane_queues, lane_vehicles, delta_t=delta_t)
        elif level == DegradationLevel.LEVEL_1_PARTIAL:
            # Level 1: Neighbor P2P or adjusted local controller
            if self.level1_controller:
                phase = self.level1_controller.step(lane_queues, lane_vehicles, delta_t=delta_t)
            else:
                # Fallback to Max Pressure or weighted baseline if Level 1 controller is omitted
                phase = self.max_pressure.step(lane_queues, lane_vehicles, delta_t=delta_t)
        else:
            # Level 0: Global / Central Coordinator
            if hasattr(self.level0_controller, "step"):
                phase = self.level0_controller.step(delta_t)
            else:
                phase = self.max_pressure.step(lane_queues, lane_vehicles, delta_t=delta_t)

        return phase, level

    def export_logs_json(self, filepath: str) -> None:
        """Exports transition history to JSON format for LLM Diagnostic Agent."""
        data = [asdict(rec) for rec in self.transition_log]
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
