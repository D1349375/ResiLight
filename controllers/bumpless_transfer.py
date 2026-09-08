"""
Bumpless Transfer (Smooth Transition) Controller Module.

THEORETICAL FOUNDATION:
-----------------------
Inspired by classical control theory (Hanus et al., 1987, "Conditioning Technique
for Controllers with Anti-Reset Windup and Bumpless Transfer").

When 5G connectivity is restored after a network outage, directly applying the cloud
MARL controller's raw timing parameters causes sudden phase duration discontinuities ("bumps"),
leading to driver confusion, aggressive deceleration, and secondary shockwave congestion.

BumplessTransferManager smooths the transition across a parameterized window T_trans (typically
3 to 5 signal cycles). The effective phase durations are smoothly blended using an S-curve:
    w(t) = 0.5 * (1 - cos(pi * t / T_trans))
    Duration_blended(p) = (1 - w(t)) * D_fallback(p) + w(t) * D_cloud(p)

At t=0, w(0)=0 (pure fallback continuity). At t=T_trans, w(T)=1 (fully aligned with cloud control).
The derivative dw/dt is 0 at both boundaries, ensuring zero initial jerk and seamless handover.
"""
import math
import logging
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("bumpless_transfer")


class TransitionMode(Enum):
    SMOOTHSTEP = "smoothstep"  # Cosine S-curve with zero derivative at boundaries
    LINEAR = "linear"          # Linear ramp


class BumplessTransferManager:
    """
    Manages smooth state and duration transitions when recovering from
    degraded / fallback operation back to nominal Level 0 control.
    """

    def __init__(
        self,
        transition_duration_s: float = 60.0,
        mode: TransitionMode = TransitionMode.SMOOTHSTEP,
    ):
        """
        Args:
            transition_duration_s: Time window (seconds) to complete the transition.
                                   Typically spans 2 to 4 full signal cycles.
            mode: Interpolation curve type (Smoothstep S-curve or Linear).
        """
        self.transition_duration_s = transition_duration_s
        self.mode = mode

        self._is_active = False
        self._elapsed_s = 0.0
        self._initial_durations: Dict[int, float] = {}
        self._target_durations: Dict[int, float] = {}

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def elapsed_s(self) -> float:
        return self._elapsed_s

    @property
    def progress_ratio(self) -> float:
        """Returns normalized progress in [0.0, 1.0]."""
        if not self._is_active or self.transition_duration_s <= 0:
            return 1.0
        return min(1.0, max(0.0, self._elapsed_s / self.transition_duration_s))

    @property
    def current_weight(self) -> float:
        """
        Returns current blending weight w in [0.0, 1.0].
        w = 0.0 corresponds to full fallback; w = 1.0 corresponds to full Level 0.
        """
        if not self._is_active:
            return 1.0

        alpha = self.progress_ratio
        if self.mode == TransitionMode.SMOOTHSTEP:
            # S-curve: 0.5 * (1 - cos(pi * alpha))
            return 0.5 * (1.0 - math.cos(math.pi * alpha))
        else:
            return alpha

    def start_transition(
        self,
        initial_durations: Dict[int, float],
        target_durations: Dict[int, float],
        transition_duration_s: Optional[float] = None,
    ) -> None:
        """
        Initiates a bumpless transfer sequence from initial fallback timings to target cloud timings.
        """
        if transition_duration_s is not None:
            self.transition_duration_s = transition_duration_s

        self._initial_durations = dict(initial_durations)
        self._target_durations = dict(target_durations)
        self._elapsed_s = 0.0
        self._is_active = True

        logger.info(
            f"Bumpless transfer initiated: duration={self.transition_duration_s}s, "
            f"initial={initial_durations}, target={target_durations}"
        )

    def step(self, delta_t: float = 1.0) -> Tuple[Dict[int, float], float, bool]:
        """
        Advances the transition by delta_t seconds.

        Returns:
            blended_durations: Dict mapping phase index to interpolated duration.
            current_weight: Blending factor w in [0.0, 1.0].
            is_completed: True if transition finished on this step.
        """
        if not self._is_active:
            return self._target_durations, 1.0, False

        self._elapsed_s += delta_t
        w = self.current_weight
        is_completed = self._elapsed_s >= self.transition_duration_s

        # Blend durations for all phases
        all_phases = set(self._initial_durations.keys()).union(self._target_durations.keys())
        blended: Dict[int, float] = {}

        for p in all_phases:
            d_init = self._initial_durations.get(p, 30.0)
            d_tgt = self._target_durations.get(p, 30.0)
            blended[p] = (1.0 - w) * d_init + w * d_tgt

        if is_completed:
            self._is_active = False
            logger.info("Bumpless transfer completed successfully. Fully aligned with Level 0.")

        return blended, w, is_completed
