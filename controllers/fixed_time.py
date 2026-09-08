"""
Fixed-Time (Pre-timed) Traffic Signal Controller.

ROLE & ARCHITECTURE BOUNDARY:
-----------------------------
This controller represents the traditional pre-timed signal logic.
Its purpose in the ResiLight evaluation framework is strictly as the
"Naive Baseline" (worst-case uncoordinated condition without dynamic degradation handling).

IMPORTANT NOTE (Do NOT confuse with Level 2 Fallback):
- Level 2 Fallback in ResiLight is MAX PRESSURE (Varaiya, 2013), an adaptive local
  rule engine based on upstream/downstream queue differentials (implemented in Phase 2).
- This FixedTimeController is NOT the Level 2 fallback; it is the non-adaptive baseline
  used to quantify how much better ResiLight performs compared to conventional static signals.
"""
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("fixed_time_controller")


class FixedTimeController:
    """
    Cycles through a predetermined sequence of phases with fixed durations.
    """

    def __init__(
        self,
        tls_id: str,
        phase_cycle: Optional[List[Tuple[int, float]]] = None,
    ):
        """
        Args:
            tls_id: ID of the traffic light to control.
            phase_cycle: Sequence of (phase_index, duration_seconds).
                         Defaults to standard 4-phase program:
                         - Phase 0 (NS Green): 30s
                         - Phase 1 (NS Yellow): 3s
                         - Phase 2 (EW Green): 30s
                         - Phase 3 (EW Yellow): 3s
        """
        self.tls_id = tls_id
        self.phase_cycle = phase_cycle or [
            (0, 30.0),  # NS Green
            (1, 3.0),   # NS Yellow
            (2, 30.0),  # EW Green
            (3, 3.0),   # EW Yellow
        ]
        self._current_index = 0
        self._time_in_phase = 0.0

    @property
    def current_phase(self) -> int:
        return self.phase_cycle[self._current_index][0]

    @property
    def target_duration(self) -> float:
        return self.phase_cycle[self._current_index][1]

    def reset(self) -> None:
        self._current_index = 0
        self._time_in_phase = 0.0

    def step(self, delta_t: float = 1.0) -> int:
        """
        Advances internal timer by delta_t seconds.
        Returns the commanded phase index for the current step.
        """
        self._time_in_phase += delta_t
        if self._time_in_phase >= self.target_duration:
            self._time_in_phase = 0.0
            self._current_index = (self._current_index + 1) % len(self.phase_cycle)

        return self.current_phase
