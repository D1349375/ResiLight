"""
TraCI Simulation Environment Wrapper.

Provides a clean, unified Python API for interacting with SUMO traffic light simulations:
- Environment lifecycle management (start/step/close/context manager)
- Intersection state observation (queue lengths, halting vehicles, occupancy)
- Traffic light control (set_phase, get_phase, phase definitions)
- Simulation-wide performance metrics collection (throughput, delay, waiting time, speed)
"""
import os
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import traci
from .sumo_config import get_binary

logger = logging.getLogger("traci_wrapper")


@dataclass
class IntersectionState:
    """Represents real-time traffic condition at a single intersection."""
    tls_id: str
    current_phase: int
    total_vehicles: int
    total_halting: int  # Vehicles queued (speed < 0.1 m/s)
    mean_speed_ms: float
    mean_occupancy_pct: float
    lane_queues: Dict[str, int] = field(default_factory=dict)
    lane_vehicles: Dict[str, int] = field(default_factory=dict)


@dataclass
class SimulationMetrics:
    """Cumulative performance metrics for the running simulation."""
    sim_time_s: float
    step_count: int
    total_arrived: int       # Vehicles that reached destination (Throughput)
    total_departed: int      # Vehicles injected into network
    active_vehicles: int     # Currently running on network
    accumulated_waiting_s: float  # Cumulative waiting time (s)
    average_speed_kmh: float


class SumoTraciWrapper:
    """
    Unified controller wrapper for SUMO traffic simulations.
    """

    def __init__(
        self,
        net_file: str,
        route_file: str,
        step_length: float = 1.0,
        gui: bool = False,
        additional_files: Optional[List[str]] = None,
        seed: Optional[int] = 42,
        extra_args: Optional[List[str]] = None,
    ):
        self.net_file = os.path.abspath(net_file)
        self.route_file = os.path.abspath(route_file)
        self.step_length = step_length
        self.gui = gui
        self.additional_files = additional_files or []
        self.seed = seed
        self.extra_args = extra_args or []

        self._is_running = False
        self._step_count = 0
        self._total_arrived = 0
        self._total_departed = 0
        self._accumulated_waiting_s = 0.0

        # Cache controlled incoming lanes per intersection
        self._tls_incoming_lanes: Dict[str, List[str]] = {}

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self) -> None:
        """Starts SUMO instance and initializes TraCI connection."""
        if self._is_running:
            logger.warning("Simulation is already running.")
            return

        sumo_bin = get_binary("sumo-gui" if self.gui else "sumo")

        cmd = [
            sumo_bin,
            "-n", self.net_file,
            "-r", self.route_file,
            "--step-length", str(self.step_length),
            "--collision.action", "none",
            "--no-warnings", "true",
            "--waiting-time-memory", "1000",
        ]

        if self.additional_files:
            cmd.extend(["-a", ",".join(self.additional_files)])

        if self.seed is not None:
            cmd.extend(["--seed", str(self.seed)])

        cmd.extend(self.extra_args)

        logger.info(f"Starting SUMO with binary: {sumo_bin}")
        traci.start(cmd)
        self._is_running = True
        self._step_count = 0
        self._total_arrived = 0
        self._total_departed = 0
        self._accumulated_waiting_s = 0.0

        # Discover intersections and their incoming lanes
        tls_ids = traci.trafficlight.getIDList()
        for tls_id in tls_ids:
            raw_lanes = traci.trafficlight.getControlledLanes(tls_id)
            # Filter to unique incoming lanes
            unique_incoming: List[str] = []
            for lane in raw_lanes:
                if lane not in unique_incoming:
                    unique_incoming.append(lane)
            self._tls_incoming_lanes[tls_id] = unique_incoming

    def close(self) -> None:
        """Closes TraCI simulation safely."""
        if self._is_running:
            try:
                traci.close()
            except Exception as e:
                logger.warning(f"Error during traci.close(): {e}")
            finally:
                self._is_running = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def step(self) -> float:
        """
        Advances simulation by one step.
        Returns current simulation time in seconds.
        """
        if not self._is_running:
            raise RuntimeError("Cannot step: simulation is not running. Call start() first.")

        traci.simulationStep()
        self._step_count += 1

        # Track arrival and departure throughput
        self._total_arrived += traci.simulation.getArrivedNumber()
        self._total_departed += traci.simulation.getDepartedNumber()

        # Accumulate waiting time of all active vehicles
        veh_ids = traci.vehicle.getIDList()
        for vid in veh_ids:
            self._accumulated_waiting_s += traci.vehicle.getWaitingTime(vid)

        return traci.simulation.getTime()

    def get_time(self) -> float:
        """Returns current simulation time (seconds)."""
        return traci.simulation.getTime()

    def get_tls_ids(self) -> List[str]:
        """Returns list of traffic light IDs in the simulation."""
        return list(self._tls_incoming_lanes.keys())

    def get_intersection_state(self, tls_id: str) -> IntersectionState:
        """
        Observes real-time state for the specified intersection.
        """
        if tls_id not in self._tls_incoming_lanes:
            raise ValueError(f"Unknown traffic light ID: '{tls_id}'")

        lanes = self._tls_incoming_lanes[tls_id]
        current_phase = traci.trafficlight.getPhase(tls_id)

        lane_queues: Dict[str, int] = {}
        lane_vehicles: Dict[str, int] = {}
        total_vehicles = 0
        total_halting = 0
        speeds: List[float] = []
        occupancies: List[float] = []

        for lane_id in lanes:
            halting = traci.lane.getLastStepHaltingNumber(lane_id)
            veh_count = traci.lane.getLastStepVehicleNumber(lane_id)
            occ = traci.lane.getLastStepOccupancy(lane_id)
            speed = traci.lane.getLastStepMeanSpeed(lane_id)

            lane_queues[lane_id] = halting
            lane_vehicles[lane_id] = veh_count
            total_vehicles += veh_count
            total_halting += halting
            occupancies.append(occ)
            if veh_count > 0:
                speeds.append(speed)

        mean_speed = sum(speeds) / len(speeds) if speeds else 13.89
        mean_occ = (sum(occupancies) / len(occupancies) * 100.0) if occupancies else 0.0

        return IntersectionState(
            tls_id=tls_id,
            current_phase=current_phase,
            total_vehicles=total_vehicles,
            total_halting=total_halting,
            mean_speed_ms=mean_speed,
            mean_occupancy_pct=mean_occ,
            lane_queues=lane_queues,
            lane_vehicles=lane_vehicles,
        )

    def set_phase(self, tls_id: str, phase_index: int) -> None:
        """
        Commands the specified traffic light to switch to target phase index.
        """
        traci.trafficlight.setPhase(tls_id, phase_index)

    def get_phase(self, tls_id: str) -> int:
        """Returns current phase index for the specified traffic light."""
        return traci.trafficlight.getPhase(tls_id)

    def get_phase_duration(self, tls_id: str) -> float:
        """Returns the remaining duration (seconds) of the current phase."""
        return traci.trafficlight.getPhaseDuration(tls_id)

    def get_metrics(self) -> SimulationMetrics:
        """
        Computes cumulative performance metrics across the entire simulation.
        """
        active_vehs = traci.vehicle.getIDList()
        active_count = len(active_vehs)

        if active_count > 0:
            speeds = [traci.vehicle.getSpeed(vid) for vid in active_vehs]
            avg_speed_ms = sum(speeds) / active_count
            avg_speed_kmh = avg_speed_ms * 3.6
        else:
            avg_speed_kmh = 0.0

        return SimulationMetrics(
            sim_time_s=traci.simulation.getTime(),
            step_count=self._step_count,
            total_arrived=self._total_arrived,
            total_departed=self._total_departed,
            active_vehicles=active_count,
            accumulated_waiting_s=self._accumulated_waiting_s,
            average_speed_kmh=avg_speed_kmh,
        )
