"""
Phase 3 Validation Tests: Bumpless Transfer (Smooth Handover).

Validates:
1. S-curve (Smoothstep) and Linear blending weight curves
2. Phase duration interpolation without overshoot or discontinuity
3. DegradationFSM recovery trigger and smooth handover lifecycle
"""
import pytest

from network_sim import NetworkQuality
from controllers.bumpless_transfer import BumplessTransferManager, TransitionMode
from controllers.degradation_fsm import DegradationFSM, DegradationLevel


def test_bumpless_transfer_smoothstep_curve():
    """Verify that Smoothstep (Cosine S-Curve) produces smooth, monotonic weights [0, 1]."""
    mgr = BumplessTransferManager(transition_duration_s=20.0, mode=TransitionMode.SMOOTHSTEP)
    mgr.start_transition(initial_durations={0: 40.0}, target_durations={0: 20.0})

    assert mgr.is_active
    assert mgr.current_weight == 0.0

    # Midpoint (t=10s out of 20s) should equal exactly 0.5
    for _ in range(10):
        blended, w, done = mgr.step(1.0)

    assert pytest.approx(w, abs=1e-3) == 0.50
    assert pytest.approx(blended[0], abs=1e-2) == 30.0  # (40 + 20) / 2
    assert not done

    # End of transition (another 10s -> t=20s)
    for _ in range(10):
        blended, w, done = mgr.step(1.0)

    assert pytest.approx(w, abs=1e-3) == 1.0
    assert pytest.approx(blended[0], abs=1e-2) == 20.0
    assert done
    assert not mgr.is_active


def test_bumpless_transfer_linear_curve():
    """Verify linear interpolation mode."""
    mgr = BumplessTransferManager(transition_duration_s=10.0, mode=TransitionMode.LINEAR)
    mgr.start_transition(initial_durations={0: 10.0}, target_durations={0: 30.0})

    for t in range(1, 11):
        blended, w, done = mgr.step(1.0)
        expected_w = t / 10.0
        assert pytest.approx(w, abs=1e-3) == expected_w
        assert pytest.approx(blended[0], abs=1e-2) == 10.0 + (30.0 - 10.0) * expected_w

    assert done


def test_bumpless_transfer_no_overshoot():
    """Verify that blended values strictly stay within [min(init, tgt), max(init, tgt)]."""
    mgr = BumplessTransferManager(transition_duration_s=15.0, mode=TransitionMode.SMOOTHSTEP)
    mgr.start_transition(initial_durations={0: 45.0, 2: 15.0}, target_durations={0: 20.0, 2: 40.0})

    while mgr.is_active:
        blended, w, _ = mgr.step(1.0)
        assert 20.0 <= blended[0] <= 45.0
        assert 15.0 <= blended[2] <= 40.0


def test_fsm_bumpless_recovery_lifecycle():
    """Verify that DegradationFSM activates and retires BumplessTransfer upon 5G link recovery."""
    fsm = DegradationFSM("J0", enable_bumpless=True)
    fsm.bumpless_manager.transition_duration_s = 20.0

    # 1. Drive FSM into Level 2 (Disconnect)
    q_cut = NetworkQuality(latency_ms=9999.0, jitter_ms=0.0, packet_loss_rate=1.0, is_connected=False)
    fsm.update_level(q_cut, current_time_s=10.0)
    assert fsm.current_level == DegradationLevel.LEVEL_2_FALLBACK
    assert not fsm.is_in_bumpless_recovery

    # 2. Restore 5G connectivity
    q_good = NetworkQuality(latency_ms=15.0, jitter_ms=2.0, packet_loss_rate=0.001, is_connected=True)
    fsm.update_level(q_good, current_time_s=30.0)
    fsm.update_level(q_good, current_time_s=31.0)

    # Should be back to Level 0 with Bumpless Transfer active
    assert fsm.current_level == DegradationLevel.LEVEL_0_NORMAL
    assert fsm.is_in_bumpless_recovery

    # 3. Step forward through the transition window
    lane_queues = {"N2J0_0": 2, "E2J0_0": 2}
    for t in range(25):
        fsm.step(
            quality=q_good,
            current_time_s=32.0 + t,
            lane_queues=lane_queues,
            delta_t=1.0,
        )

    # After 25 steps (> 20s transition window), Bumpless Transfer should complete
    assert not fsm.is_in_bumpless_recovery
