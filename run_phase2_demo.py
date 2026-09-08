"""
Phase 2 Demonstration Script: 5G Link Degradation & Max Pressure Fallback.

Demonstrates:
1. Normal 5G URLLC operation (Level 0).
2. Fiber-cut disruption injected at t=60s (Level 2 Max Pressure takes over).
3. Network restored at t=120s (Level 0 recovery).
4. Side-by-side comparison: ResiLight Dynamic Degradation vs Naive Static Baseline.
5. Audit trail log export for the LLM Diagnostic Agent.

Usage:
    python run_phase2_demo.py           # Headless CLI
    python run_phase2_demo.py --gui     # With SUMO-GUI
"""
import os
import sys
import time
import argparse
import logging

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from envs import build_4way_network, build_4way_demand, SumoTraciWrapper
from network_sim import NetworkQualitySimulator, DegradationEvent
from controllers import DegradationFSM, DegradationLevel, FixedTimeController

logging.basicConfig(level=logging.WARNING)


def run_resilight_run(
    net_file: str,
    rou_file: str,
    tls_id: str,
    duration_s: int,
    cut_start_s: int,
    cut_duration_s: int,
    gui: bool = False,
):
    net_sim = NetworkQualitySimulator(base_latency_ms=15.0, base_jitter_ms=2.0, base_loss_rate=0.001)
    net_sim.inject_event(DegradationEvent(
        name="Fiber_Cut_Incident",
        start_step=cut_start_s,
        duration_steps=cut_duration_s,
        latency_ms=9999.0,
        jitter_ms=0.0,
        packet_loss_rate=1.0,
        is_connected=False,
    ))

    fsm = DegradationFSM(tls_id)

    header = f"{'Time':>6} | {'Link QoS':>16} | {'Level':>16} | {'Phase':>5} | {'Queue':>6} | {'Thruput':>7} | {'AvgSpd':>8} | {'WaitTime':>9}"
    divider = "-" * len(header)
    print("\n[ResiLight Active Degradation Run]")
    print(divider)
    print(header)
    print(divider)

    with SumoTraciWrapper(net_file, rou_file, step_length=1.0, gui=gui) as sim:
        sim_time = 0.0
        while sim_time < duration_s:
            step_idx = int(sim_time)
            net_sim.step(step_idx)
            link_q = net_sim.get_quality(tls_id)

            state = sim.get_intersection_state(tls_id)
            target_phase, active_level = fsm.step(
                quality=link_q,
                current_time_s=sim_time,
                lane_queues=state.lane_queues,
                lane_vehicles=state.lane_vehicles,
                active_vehicles=state.total_vehicles,
                total_queued=state.total_halting,
                delta_t=1.0,
            )

            sim.set_phase(tls_id, target_phase)
            sim_time = sim.step()

            if int(sim_time) % 15 == 0:
                metrics = sim.get_metrics()
                qos_str = "DISCONNECTED" if not link_q.is_connected else f"Lat={link_q.latency_ms:.0f}ms"
                level_str = f"L{active_level.value}:{active_level.name.split('_')[2]}"
                print(
                    f"{sim_time:>5.0f}s | "
                    f"{qos_str:>16} | "
                    f"{level_str:>16} | "
                    f"{state.current_phase:>5} | "
                    f"{state.total_halting:>6} | "
                    f"{metrics.total_arrived:>7} | "
                    f"{metrics.average_speed_kmh:>6.1f}km | "
                    f"{metrics.accumulated_waiting_s:>7.0f}s"
                )

        final_metrics = sim.get_metrics()

    print(divider)
    return final_metrics, fsm


def run_baseline_run(net_file: str, rou_file: str, tls_id: str, duration_s: int):
    controller = FixedTimeController(tls_id, phase_cycle=[(0, 30.0), (1, 3.0), (2, 30.0), (3, 3.0)])
    with SumoTraciWrapper(net_file, rou_file, step_length=1.0) as sim:
        sim_time = 0.0
        while sim_time < duration_s:
            target_phase = controller.step(1.0)
            sim.set_phase(tls_id, target_phase)
            sim_time = sim.step()
        final_metrics = sim.get_metrics()
    return final_metrics


def main():
    parser = argparse.ArgumentParser(description="ResiLight Phase 2 Demo")
    parser.add_argument("--duration", type=int, default=150, help="Total simulation duration (s)")
    parser.add_argument("--cut-start", type=int, default=45, help="Start time of fiber cut disruption (s)")
    parser.add_argument("--cut-duration", type=int, default=60, help="Duration of disruption (s)")
    parser.add_argument("--gui", action="store_true", help="Launch SUMO-GUI")
    args = parser.parse_args()

    net_dir = os.path.join(os.path.dirname(__file__), "sumo_nets", "benchmark")
    net_file, tls_id = build_4way_network(net_dir)
    rou_file = build_4way_demand(net_dir, duration_s=args.duration + 60, main_vph=950.0, side_vph=550.0)

    print("=" * 85)
    print("ResiLight Phase 2: 5G MEC Resilience & Dynamic Fallback Demo")
    print("=" * 85)
    print(f"Disruption Scenario: Fiber cut between t={args.cut_start}s and t={args.cut_start + args.cut_duration}s")

    resi_metrics, fsm = run_resilight_run(
        net_file, rou_file, tls_id, args.duration, args.cut_start, args.cut_duration, gui=args.gui
    )

    print("\nRunning Naive Baseline (Static Pre-timed Signal) for comparison...")
    base_metrics = run_baseline_run(net_file, rou_file, tls_id, args.duration)

    # Export audit log
    log_file = os.path.join(os.path.dirname(__file__), "sim_output", "degradation_events.json")
    fsm.export_logs_json(log_file)
    print(f"\n[+] Degradation event log exported to: {os.path.relpath(log_file)}")

    # Comparison summary table
    print("\n" + "=" * 85)
    print("PERFORMANCE COMPARISON SUMMARY (Under 60s 5G Link Failure)")
    print("=" * 85)
    print(f"{'Performance Metric':<30} | {'Naive Baseline':>18} | {'ResiLight (Ours)':>18} | {'Improvement':>12}")
    print("-" * 85)

    delay_diff = ((base_metrics.accumulated_waiting_s - resi_metrics.accumulated_waiting_s) / max(1.0, base_metrics.accumulated_waiting_s)) * 100
    thru_diff = ((resi_metrics.total_arrived - base_metrics.total_arrived) / max(1, base_metrics.total_arrived)) * 100
    spd_diff = ((resi_metrics.average_speed_kmh - base_metrics.average_speed_kmh) / max(1.0, base_metrics.average_speed_kmh)) * 100

    print(f"{'Throughput (Arrived Vehicles)':<30} | {base_metrics.total_arrived:>18} | {resi_metrics.total_arrived:>18} | {thru_diff:>+11.1f}%")
    print(f"{'Cumulative Delay (veh-seconds)':<30} | {base_metrics.accumulated_waiting_s:>18.1f} | {resi_metrics.accumulated_waiting_s:>18.1f} | {-delay_diff:>+11.1f}%")
    print(f"{'Average Network Speed (km/h)':<30} | {base_metrics.average_speed_kmh:>18.1f} | {resi_metrics.average_speed_kmh:>18.1f} | {spd_diff:>+11.1f}%")
    print("=" * 85)
    print(f"[OK] Audit Log Count: {len(fsm.transition_log)} transition events recorded.")
    for rec in fsm.transition_log:
        print(f"   -> [{rec.timestamp_s:.0f}s] Level {rec.from_level} -> Level {rec.to_level} | Reason: {rec.reason}")
    print("=" * 85)


if __name__ == "__main__":
    main()
