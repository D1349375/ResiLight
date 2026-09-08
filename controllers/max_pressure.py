"""
Max Pressure Traffic Signal Controller (Level 2 Fallback).

THEORY & SPECIFICATION:
-----------------------
Based on Varaiya (2013), "The max-pressure controller for arbitrary networks
of signalized intersections".

At each decision step, the controller calculates the "pressure" of each candidate green phase:
    Pressure(p) = sum_{l in In(p)} Queue(l) - sum_{m in Out(p)} Queue(m)

The phase with the maximum positive pressure is selected. If all pressures are non-positive,
the controller maintains the current phase or serves the lane with highest demand.

SAFETY CONSTRAINTS:
-------------------
1. Minimum Green Time (`min_green_s` = 10s): Prevents rapid oscillation (chattering).
2. Yellow Clearance Transition (`yellow_s` = 3s): Mandates safe clearance phase
   between conflicting green phases.
3. Zero Network Dependency: Evaluated 100% locally on edge RSU using local loop detectors / CCTV.
"""
import logging
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("max_pressure")


class MaxPressureController:
    """
    Decentralized Max Pressure controller for a single intersection.
    Serves as Level 2 Fallback in the ResiLight architecture.
    """

    def __init__(
        self,
        tls_id: str,
        in_lanes_phase_0: Optional[List[str]] = None,
        out_lanes_phase_0: Optional[List[str]] = None,
        in_lanes_phase_2: Optional[List[str]] = None,
        out_lanes_phase_2: Optional[List[str]] = None,
        min_green_s: float = 10.0,
        yellow_s: float = 3.0,
        max_green_s: float = 60.0,
    ):
        self.tls_id = tls_id
        self.min_green_s = min_green_s
        self.yellow_s = yellow_s
        self.max_green_s = max_green_s

        # Default lane assignments for standard 4-way intersection
        # Phase 0: North-South Green (in: N2J0, S2J0; out: J02N, J02S)
        # Phase 2: East-West Green   (in: E2J0, W2J0; out: J02E, J02W)
        self.in_lanes_phase_0 = in_lanes_phase_0 or [
            "N2J0_0", "N2J0_1", "S2J0_0", "S2J0_1"
        ]
        self.out_lanes_phase_0 = out_lanes_phase_0 or [
            "J02N_0", "J02N_1", "J02S_0", "J02S_1"
        ]
        self.in_lanes_phase_2 = in_lanes_phase_2 or [
            "E2J0_0", "E2J0_1", "W2J0_0", "W2J0_1"
        ]
        self.out_lanes_phase_2 = out_lanes_phase_2 or [
            "J02E_0", "J02E_1", "J02W_0", "J02W_1"
        ]

        # Phase transition mapping for standard 4-phase:
        # Green 0 -> Yellow 1 -> Green 2 -> Yellow 3 -> Green 0
        self.green_to_yellow = {0: 1, 2: 3}
        self.yellow_to_green = {1: 2, 3: 0}

        self.current_phase = 0
        self.target_green_phase = 0
        self.time_in_current_phase = 0.0
        self.is_in_yellow = False

    def reset(self, initial_phase: int = 0) -> None:
        self.current_phase = initial_phase
        self.target_green_phase = initial_phase
        self.time_in_current_phase = 0.0
        self.is_in_yellow = False

    def calculate_phase_pressure(
        self,
        in_lanes: List[str],
        out_lanes: List[str],
        lane_queues: Dict[str, int],
        lane_vehicles: Optional[Dict[str, int]] = None,
    ) -> float:
        """
        Calculates net pressure = upstream queue - downstream occupancy.
        Uses halting vehicles (queued) for upstream, vehicle count for downstream.
        """
        in_pressure = sum(lane_queues.get(lane, 0) for lane in in_lanes)
        out_penalty = 0.5 * sum(lane_queues.get(lane, 0) for lane in out_lanes)
        return float(in_pressure - out_penalty)

    def select_best_green_phase(
        self,
        lane_queues: Dict[str, int],
        lane_vehicles: Optional[Dict[str, int]] = None,
    ) -> Tuple[int, Dict[int, float]]:
        """
        Evaluates pressures for candidate green phases (Phase 0 vs Phase 2).
        Returns (best_phase, pressure_dict).
        """
        p0 = self.calculate_phase_pressure(
            self.in_lanes_phase_0, self.out_lanes_phase_0, lane_queues, lane_vehicles
        )
        p2 = self.calculate_phase_pressure(
            self.in_lanes_phase_2, self.out_lanes_phase_2, lane_queues, lane_vehicles
        )

        pressures = {0: p0, 2: p2}

        # If current phase is green and has not exceeded max green, require a margin to switch
        # to prevent unnecessary switching when pressures are close
        margin = 1.0
        if self.current_phase == 0:
            best_phase = 2 if (p2 > p0 + margin) else 0
        elif self.current_phase == 2:
            best_phase = 0 if (p0 > p2 + margin) else 2
        else:
            best_phase = 0 if p0 >= p2 else 2

        return best_phase, pressures

    def step(
        self,
        lane_queues: Dict[str, int],
        lane_vehicles: Optional[Dict[str, int]] = None,
        delta_t: float = 1.0,
    ) -> int:
        """
        Advances the controller by delta_t seconds, applying safety constraints
        and Max Pressure decision logic. Returns the commanded phase index.
        """
        self.time_in_current_phase += delta_t

        # Case 1: Currently in yellow transition phase
        if self.is_in_yellow:
            if self.time_in_current_phase >= self.yellow_s:
                # Yellow expired -> switch to the intended target green phase
                self.current_phase = self.target_green_phase
                self.is_in_yellow = False
                self.time_in_current_phase = 0.0
            return self.current_phase

        # Case 2: Currently in green phase
        # Check minimum green safety constraint
        if self.time_in_current_phase < self.min_green_s:
            # Must stay green
            return self.current_phase

        # Minimum green satisfied; evaluate pressures
        best_green, _ = self.select_best_green_phase(lane_queues, lane_vehicles)

        # Force switch if max green reached
        if self.time_in_current_phase >= self.max_green_s:
            best_green = 2 if self.current_phase == 0 else 0

        if best_green != self.current_phase:
            # Decision to switch -> enter yellow clearance phase first!
            yellow_phase = self.green_to_yellow.get(self.current_phase, 1)
            self.target_green_phase = best_green
            self.current_phase = yellow_phase
            self.is_in_yellow = True
            self.time_in_current_phase = 0.0

        return self.current_phase
