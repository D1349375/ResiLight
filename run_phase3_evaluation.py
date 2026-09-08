"""
Phase 3 Evaluation & Visualization Script: Bumpless Transfer vs Hard Switch.

Runs three conditions over a 5G link failure & recovery scenario:
1. Naive Baseline (Static Pre-timed signal without degradation)
2. Hard Switch (Abrupt transition back to cloud control)
3. ResiLight Bumpless Transfer (Smooth S-curve handover, Ours)

Generates publication-ready figures saved in `results/`:
- `results/bumpless_vs_hard_switch.png`
- `results/resilience_performance_curves.png`

Usage:
    python run_phase3_evaluation.py
"""
import os
import sys
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")  # Non-interactive headless backend for automated script execution
import matplotlib.pyplot as plt
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from envs import build_4way_network, build_4way_demand, SumoTraciWrapper
from network_sim import NetworkQualitySimulator, DegradationEvent
from controllers import DegradationFSM, DegradationLevel, FixedTimeController

logging.basicConfig(level=logging.WARNING)


@dataclass
class SimulationTrace:
    times: List[float] = field(default_factory=list)
    queues: List[int] = field(default_factory=list)
    delays: List[float] = field(default_factory=list)
    speeds: List[float] = field(default_factory=list)
    phases: List[int] = field(default_factory=list)
    phase_durations: List[float] = field(default_factory=list)
    weights: List[float] = field(default_factory=list)
    levels: List[int] = field(default_factory=list)


def run_simulation(
    net_file: str,
    rou_file: str,
    tls_id: str,
    duration_s: int,
    cut_start_s: int,
    cut_duration_s: int,
    mode: str = "bumpless",  # "baseline", "hard_switch", "bumpless"
) -> SimulationTrace:
    trace = SimulationTrace()

    net_sim = NetworkQualitySimulator(base_latency_ms=15.0, base_jitter_ms=2.0, base_loss_rate=0.001)
    net_sim.inject_event(DegradationEvent(
        name="Fiber_Cut_Disruption",
        start_step=cut_start_s,
        duration_steps=cut_duration_s,
        latency_ms=9999.0,
        jitter_ms=0.0,
        packet_loss_rate=1.0,
        is_connected=False,
    ))

    if mode == "baseline":
        controller = FixedTimeController(tls_id, phase_cycle=[(0, 30.0), (1, 3.0), (2, 30.0), (3, 3.0)])
    else:
        enable_bumpless = (mode == "bumpless")
        fsm = DegradationFSM(tls_id, enable_bumpless=enable_bumpless)
        fsm.bumpless_manager.transition_duration_s = 40.0

    with SumoTraciWrapper(net_file, rou_file, step_length=1.0) as sim:
        sim_time = 0.0
        while sim_time < duration_s:
            step_idx = int(sim_time)
            net_sim.step(step_idx)
            link_q = net_sim.get_quality(tls_id)

            state = sim.get_intersection_state(tls_id)
            metrics = sim.get_metrics()

            if mode == "baseline":
                target_phase = controller.step(1.0)
                active_level = 0
                weight = 1.0
                curr_duration = 30.0
            else:
                target_phase, active_level = fsm.step(
                    quality=link_q,
                    current_time_s=sim_time,
                    lane_queues=state.lane_queues,
                    lane_vehicles=state.lane_vehicles,
                    active_vehicles=state.total_vehicles,
                    total_queued=state.total_halting,
                    delta_t=1.0,
                )
                weight = fsm.bumpless_manager.current_weight if fsm.enable_bumpless and fsm.bumpless_manager.is_active else (1.0 if active_level == DegradationLevel.LEVEL_0_NORMAL else 0.0)
                curr_duration = fsm.level0_controller.phase_cycle[0][1] if hasattr(fsm.level0_controller, "phase_cycle") else 30.0

            sim.set_phase(tls_id, target_phase)
            sim_time = sim.step()

            # Record trace point
            trace.times.append(sim_time)
            trace.queues.append(state.total_halting)
            trace.delays.append(metrics.accumulated_waiting_s)
            trace.speeds.append(metrics.average_speed_kmh)
            trace.phases.append(target_phase)
            trace.phase_durations.append(curr_duration)
            trace.weights.append(weight)
            trace.levels.append(int(active_level))

    return trace


def plot_evaluation_charts(
    trace_base: SimulationTrace,
    trace_hard: SimulationTrace,
    trace_bump: SimulationTrace,
    cut_start: int,
    cut_duration: int,
    output_dir: str,
):
    os.makedirs(output_dir, exist_ok=True)
    cut_end = cut_start + cut_duration

    # -------------------------------------------------------------
    # Figure 1: Bumpless Transfer vs Hard Switch Handover Dynamics
    # -------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)

    # Subplot 1: Phase Duration Trajectory
    ax1.plot(trace_hard.times, trace_hard.phase_durations, label="Direct Hard Switch (Abrupt Jump)", color="#d9534f", linestyle="--", linewidth=2.0)
    ax1.plot(trace_bump.times, trace_bump.phase_durations, label="ResiLight Bumpless Transfer (Smooth S-Curve)", color="#2b8a3e", linewidth=2.5)
    ax1.axvspan(cut_start, cut_end, color="#ffecb3", alpha=0.5, label="5G Outage (Level 2 Fallback)")
    ax1.axvspan(cut_end, cut_end + 40, color="#e8f5e9", alpha=0.5, label="Handover Window (Bumpless)")
    ax1.set_ylabel("Phase 0 Duration (s)", fontsize=11, fontweight="bold")
    ax1.set_title("ResiLight: Bumpless Handover vs Hard Switch Timing Trajectory", fontsize=13, fontweight="bold")
    ax1.legend(loc="upper left", framealpha=0.9)
    ax1.grid(True, linestyle=":", alpha=0.6)

    # Subplot 2: Blending Weight w(t)
    ax2.plot(trace_hard.times, trace_hard.weights, label="Hard Switch Weight", color="#d9534f", linestyle="--", linewidth=2.0)
    ax2.plot(trace_bump.times, trace_bump.weights, label="Bumpless S-Curve Weight w(t)", color="#1971c2", linewidth=2.5)
    ax2.axvspan(cut_start, cut_end, color="#ffecb3", alpha=0.5)
    ax2.axvspan(cut_end, cut_end + 40, color="#e8f5e9", alpha=0.5)
    ax2.set_xlabel("Simulation Time (s)", fontsize=11, fontweight="bold")
    ax2.set_ylabel("Level 0 Weight w(t)", fontsize=11, fontweight="bold")
    ax2.set_ylim(-0.05, 1.1)
    ax2.legend(loc="upper left", framealpha=0.9)
    ax2.grid(True, linestyle=":", alpha=0.6)

    plt.tight_layout()
    fig1_path = os.path.join(output_dir, "bumpless_vs_hard_switch.png")
    plt.savefig(fig1_path, dpi=200)
    plt.close()
    print(f"[+] Figure 1 saved: {os.path.relpath(fig1_path)}")

    # -------------------------------------------------------------
    # Figure 2: Cumulative Delay and Active Queue Under Disruption
    # -------------------------------------------------------------
    fig2, (bx1, bx2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)

    # Subplot 1: Cumulative Delay
    bx1.plot(trace_base.times, trace_base.delays, label="Naive Baseline (No Degradation)", color="#868e96", linestyle=":", linewidth=2.0)
    bx1.plot(trace_hard.times, trace_hard.delays, label="Hard Switch", color="#d9534f", linestyle="--", linewidth=2.0)
    bx1.plot(trace_bump.times, trace_bump.delays, label="ResiLight (Bumpless)", color="#2b8a3e", linewidth=2.5)
    bx1.axvspan(cut_start, cut_end, color="#ffecb3", alpha=0.5, label="5G Outage Window")
    bx1.set_ylabel("Cumulative Delay (veh-s)", fontsize=11, fontweight="bold")
    bx1.set_title("ResiLight: Network Delay Progression Under 5G Disruption", fontsize=13, fontweight="bold")
    bx1.legend(loc="upper left", framealpha=0.9)
    bx1.grid(True, linestyle=":", alpha=0.6)

    # Subplot 2: Instantaneous Halting Queues
    bx2.plot(trace_base.times, trace_base.queues, label="Naive Baseline Queue", color="#868e96", linestyle=":", linewidth=1.8)
    bx2.plot(trace_hard.times, trace_hard.queues, label="Hard Switch Queue", color="#d9534f", linestyle="--", linewidth=1.8)
    bx2.plot(trace_bump.times, trace_bump.queues, label="ResiLight Queue (Max Pressure + Bumpless)", color="#2b8a3e", linewidth=2.2)
    bx2.axvspan(cut_start, cut_end, color="#ffecb3", alpha=0.5)
    bx2.set_xlabel("Simulation Time (s)", fontsize=11, fontweight="bold")
    bx2.set_ylabel("Queued Vehicles", fontsize=11, fontweight="bold")
    bx2.legend(loc="upper left", framealpha=0.9)
    bx2.grid(True, linestyle=":", alpha=0.6)

    plt.tight_layout()
    fig2_path = os.path.join(output_dir, "resilience_performance_curves.png")
    plt.savefig(fig2_path, dpi=200)
    plt.close()
    print(f"[+] Figure 2 saved: {os.path.relpath(fig2_path)}")


def main():
    duration_s = 160
    cut_start_s = 40
    cut_duration_s = 50

    net_dir = os.path.join(os.path.dirname(__file__), "sumo_nets", "benchmark")
    net_file, tls_id = build_4way_network(net_dir)
    rou_file = build_4way_demand(net_dir, duration_s=duration_s + 60, main_vph=900.0, side_vph=500.0)

    print("=" * 75)
    print("ResiLight Phase 3: Bumpless Transfer Comparative Evaluation")
    print("=" * 75)
    print(f"Scenario: 5G link severed at t={cut_start_s}s for {cut_duration_s}s (Recovery at t={cut_start_s + cut_duration_s}s)")

    print("\n[1/3] Running Condition 1: Naive Static Baseline...")
    trace_base = run_simulation(net_file, rou_file, tls_id, duration_s, cut_start_s, cut_duration_s, mode="baseline")

    print("[2/3] Running Condition 2: Hard Switch (Abrupt jump upon recovery)...")
    trace_hard = run_simulation(net_file, rou_file, tls_id, duration_s, cut_start_s, cut_duration_s, mode="hard_switch")

    print("[3/3] Running Condition 3: ResiLight Bumpless Transfer (Smooth S-curve handover)...")
    trace_bump = run_simulation(net_file, rou_file, tls_id, duration_s, cut_start_s, cut_duration_s, mode="bumpless")

    results_dir = os.path.join(os.path.dirname(__file__), "results")
    plot_evaluation_charts(trace_base, trace_hard, trace_bump, cut_start_s, cut_duration_s, results_dir)

    print("\n" + "=" * 75)
    print("PHASE 3 EVALUATION METRICS SUMMARY")
    print("=" * 75)
    final_delay_base = trace_base.delays[-1]
    final_delay_hard = trace_hard.delays[-1]
    final_delay_bump = trace_bump.delays[-1]

    print(f"Final Cumulative Delay:")
    print(f"  - Naive Baseline : {final_delay_base:.1f} veh-s")
    print(f"  - Hard Switch    : {final_delay_hard:.1f} veh-s ({(final_delay_hard - final_delay_base)/final_delay_base*100:+.1f}% vs baseline)")
    print(f"  - ResiLight (Ours): {final_delay_bump:.1f} veh-s ({(final_delay_bump - final_delay_base)/final_delay_base*100:+.1f}% vs baseline)")

    improvement = ((final_delay_base - final_delay_bump) / final_delay_base) * 100
    print(f"\n[OK] ResiLight overall delay reduction: {improvement:.1f}% under severe 5G link failure.")
    print("=" * 75)


if __name__ == "__main__":
    main()
