"""
Phase 2 Validation Tests: Core Degradation & Max Pressure Architecture.

Validates:
1. 5G Network Quality Simulator (event injection, link-cut, delay, packet loss)
2. Max Pressure Controller (pressure formula, min green enforcement, yellow clearance)
3. Three-Level Degradation FSM (threshold mapping, debounce, audit trail logging)
4. End-to-end integration: SUMO simulation with real-time fiber cut injection & Level 2 recovery
"""
import os
import shutil
import tempfile
import pytest

from envs import build_4way_network, build_4way_demand, SumoTraciWrapper
from network_sim import NetworkQuality, DegradationEvent, NetworkQualitySimulator
from controllers.max_pressure import MaxPressureController
from controllers.degradation_fsm import DegradationFSM, DegradationLevel


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="resilight_phase2_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_network_quality_simulator_events():
    """Verify that NetworkQualitySimulator accurately handles scheduled events."""
    sim = NetworkQualitySimulator(base_latency_ms=15.0, base_jitter_ms=2.0, base_loss_rate=0.001)

    # Initial state
    q0 = sim.get_quality()
    assert q0.is_connected
    assert q0.latency_ms == 15.0

    # Inject fiber cut from step 50 to 100
    event = DegradationEvent(
        name="fiber_cut",
        start_step=50,
        duration_steps=50,
        latency_ms=9999.0,
        jitter_ms=0.0,
        packet_loss_rate=1.0,
        is_connected=False,
    )
    sim.inject_event(event)

    sim.step(20)
    assert sim.get_quality().is_connected

    sim.step(50)
    q_cut = sim.get_quality()
    assert not q_cut.is_connected
    assert q_cut.packet_loss_rate == 1.0
    assert not sim.can_deliver_packet()

    sim.step(105)
    q_recovered = sim.get_quality()
    assert q_recovered.is_connected
    assert q_recovered.latency_ms == 15.0


def test_max_pressure_pressure_calculation():
    """Verify net pressure calculation formula: upstream queue minus downstream queue."""
    ctrl = MaxPressureController("J0")

    # Heavy NS queue, zero EW queue
    ns_heavy = {
        "N2J0_0": 10, "N2J0_1": 8, "S2J0_0": 12, "S2J0_1": 10,
        "E2J0_0": 0, "E2J0_1": 0, "W2J0_0": 0, "W2J0_1": 0,
        "J02N_0": 0, "J02N_1": 0, "J02S_0": 0, "J02S_1": 0,
        "J02E_0": 0, "J02E_1": 0, "J02W_0": 0, "J02W_1": 0,
    }

    best_phase, pressures = ctrl.select_best_green_phase(ns_heavy)
    assert best_phase == 0
    assert pressures[0] == 40.0
    assert pressures[2] == 0.0

    # Heavy EW queue
    ew_heavy = {
        "N2J0_0": 1, "N2J0_1": 0, "S2J0_0": 1, "S2J0_1": 0,
        "E2J0_0": 15, "E2J0_1": 10, "W2J0_0": 12, "W2J0_1": 8,
        "J02N_0": 0, "J02N_1": 0, "J02S_0": 0, "J02S_1": 0,
        "J02E_0": 0, "J02E_1": 0, "J02W_0": 0, "J02W_1": 0,
    }
    best_phase_ew, pressures_ew = ctrl.select_best_green_phase(ew_heavy)
    assert best_phase_ew == 2
    assert pressures_ew[2] > pressures_ew[0]


def test_max_pressure_safety_constraints():
    """Verify that min green and yellow clearance constraints are strictly enforced."""
    ctrl = MaxPressureController("J0", min_green_s=8.0, yellow_s=3.0)
    assert ctrl.current_phase == 0

    # Massive EW queue demanding immediate switch
    opposing_demand = {
        "N2J0_0": 0, "N2J0_1": 0, "S2J0_0": 0, "S2J0_1": 0,
        "E2J0_0": 50, "E2J0_1": 50, "W2J0_0": 50, "W2J0_1": 50,
    }

    # First 7 seconds: must stay in Phase 0 due to min_green_s=8
    for _ in range(7):
        phase = ctrl.step(opposing_demand, delta_t=1.0)
        assert phase == 0

    # At step 8 (time=8s >= min_green): enters Yellow phase (Phase 1)
    phase_switch = ctrl.step(opposing_demand, delta_t=1.0)
    assert phase_switch == 1  # Yellow 1
    assert ctrl.is_in_yellow

    # During yellow (3 seconds): must hold yellow
    assert ctrl.step(opposing_demand, delta_t=1.0) == 1
    assert ctrl.step(opposing_demand, delta_t=1.0) == 1

    # Next step: yellow expired -> switches to Green 2
    assert ctrl.step(opposing_demand, delta_t=1.0) == 2
    assert not ctrl.is_in_yellow


def test_degradation_fsm_transitions_and_logging(temp_dir):
    """Verify 3-level transitions and structured event log output."""
    fsm = DegradationFSM("J0", debounce_steps=2)
    assert fsm.current_level == DegradationLevel.LEVEL_0_NORMAL

    # Moderate degradation -> Level 1
    q_mod = NetworkQuality(latency_ms=120.0, jitter_ms=15.0, packet_loss_rate=0.04, is_connected=True)
    fsm.update_level(q_mod, current_time_s=10.0)
    fsm.update_level(q_mod, current_time_s=11.0)
    assert fsm.current_level == DegradationLevel.LEVEL_1_PARTIAL

    # Disconnect -> Level 2
    q_disc = NetworkQuality(latency_ms=9999.0, jitter_ms=0.0, packet_loss_rate=1.0, is_connected=False)
    fsm.update_level(q_disc, current_time_s=25.0)
    assert fsm.current_level == DegradationLevel.LEVEL_2_FALLBACK

    # Recovery -> Level 0
    q_good = NetworkQuality(latency_ms=12.0, jitter_ms=2.0, packet_loss_rate=0.001, is_connected=True)
    fsm.update_level(q_good, current_time_s=40.0)
    fsm.update_level(q_good, current_time_s=41.0)
    assert fsm.current_level == DegradationLevel.LEVEL_0_NORMAL

    # Verify audit logs
    assert len(fsm.transition_log) == 3
    log_path = os.path.join(temp_dir, "transition_log.json")
    fsm.export_logs_json(log_path)
    assert os.path.isfile(log_path)


def test_end_to_end_degradation_in_sumo(temp_dir):
    """
    Full end-to-end integration:
    Run SUMO, inject a 5G link failure event at t=30s,
    verify that FSM drops to Level 2 (Max Pressure) and controls the junction successfully.
    """
    net_file, tls_id = build_4way_network(temp_dir)
    rou_file = build_4way_demand(temp_dir, duration_s=120.0, main_vph=900, side_vph=500)

    net_sim = NetworkQualitySimulator(base_latency_ms=15.0, base_jitter_ms=2.0, base_loss_rate=0.001)
    # Inject fiber cut from step 25 to 55 (30 steps duration)
    net_sim.inject_event(DegradationEvent(
        name="fiber_cut_scenario",
        start_step=25,
        duration_steps=30,
        latency_ms=9999.0,
        jitter_ms=0.0,
        packet_loss_rate=1.0,
        is_connected=False,
    ))

    fsm = DegradationFSM(tls_id)
    levels_observed = []

    with SumoTraciWrapper(net_file, rou_file, step_length=1.0) as sim:
        for step_idx in range(70):
            current_time = sim.get_time()
            net_sim.step(step_idx)
            link_quality = net_sim.get_quality(tls_id)

            state = sim.get_intersection_state(tls_id)
            target_phase, active_level = fsm.step(
                quality=link_quality,
                current_time_s=current_time,
                lane_queues=state.lane_queues,
                lane_vehicles=state.lane_vehicles,
                active_vehicles=state.total_vehicles,
                total_queued=state.total_halting,
                delta_t=1.0,
            )

            sim.set_phase(tls_id, target_phase)
            sim.step()
            levels_observed.append(active_level)

    # Validate that the simulation experienced Level 0 initially, dropped to Level 2 during the cut,
    # and returned to Level 0 upon recovery.
    assert DegradationLevel.LEVEL_0_NORMAL in levels_observed[:20]
    assert DegradationLevel.LEVEL_2_FALLBACK in levels_observed[26:50]
    assert DegradationLevel.LEVEL_0_NORMAL in levels_observed[60:]
    assert len(fsm.transition_log) >= 2
