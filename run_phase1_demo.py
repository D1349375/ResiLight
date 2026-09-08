"""
Phase 1 End-to-End Demonstration Script.

Runs a complete SUMO traffic light simulation on the 4-way benchmark network,
driven by the FixedTimeController (Naive Baseline).

Usage:
    python run_phase1_demo.py           # Runs headless
    python run_phase1_demo.py --gui     # Runs with SUMO-GUI
"""
import os
import time
import argparse
import logging

import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from envs import (
    build_4way_network,
    build_4way_demand,
    SumoTraciWrapper,
)
from controllers.fixed_time import FixedTimeController

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Phase1Demo")


def run_demo(duration_s: int = 180, gui: bool = False, main_vph: float = 800.0, side_vph: float = 450.0):
    net_dir = os.path.join(os.path.dirname(__file__), "sumo_nets", "benchmark")
    os.makedirs(net_dir, exist_ok=True)

    print("=" * 70)
    print("ResiLight Phase 1: Shared Infrastructure & TraCI Baseline Demo")
    print("=" * 70)
    print(f"Target Directory: {net_dir}")
    print(f"Simulation Mode : {'SUMO-GUI' if gui else 'Headless (CLI)'}")
    print(f"Duration        : {duration_s} seconds")
    print(f"Traffic Demand  : Arterial {main_vph:.0f} vph | Side Street {side_vph:.0f} vph")
    print("=" * 70)

    # 1. Generate network and route definitions
    print("\n[1/3] Generating benchmark network and vehicle routes...")
    net_file, tls_id = build_4way_network(net_dir)
    rou_file = build_4way_demand(net_dir, duration_s=duration_s + 60, main_vph=main_vph, side_vph=side_vph)
    print(f"  [+] Network file : {os.path.relpath(net_file)}")
    print(f"  [+] Route file   : {os.path.relpath(rou_file)}")
    print(f"  [+] Traffic Light: {tls_id}")

    # 2. Instantiate FixedTimeController (Naive Baseline)
    # Standard cycle: NS Green (25s), NS Yellow (3s), EW Green (20s), EW Yellow (3s)
    cycle = [(0, 25.0), (1, 3.0), (2, 20.0), (3, 3.0)]
    controller = FixedTimeController(tls_id, phase_cycle=cycle)
    print("\n[2/3] Initializing FixedTimeController (Naive Baseline)...")
    print(f"  [+] Cycle Structure: {cycle} (Total cycle = {sum(d for _, d in cycle)}s)")
    print("  [NOTE] This controller serves as the baseline comparison against adaptive control.")

    # 3. Start simulation and execution loop
    print("\n[3/3] Starting SUMO TraCI simulation loop...")
    header = f"{'Sim Time':>9} | {'Phase':>5} | {'Active Veh':>10} | {'Queued Veh':>10} | {'Throughput':>10} | {'Avg Spd (km/h)':>14} | {'Total Delay(s)':>14}"
    divider = "-" * len(header)
    print(divider)
    print(header)
    print(divider)

    start_real_time = time.time()
    with SumoTraciWrapper(net_file, rou_file, step_length=1.0, gui=gui) as sim:
        sim_time = 0.0
        while sim_time < duration_s:
            # Controller selects phase
            target_phase = controller.step(1.0)
            sim.set_phase(tls_id, target_phase)

            # Step simulation forward
            sim_time = sim.step()

            # Report every 15 seconds
            if int(sim_time) % 15 == 0:
                state = sim.get_intersection_state(tls_id)
                metrics = sim.get_metrics()
                print(
                    f"{sim_time:>8.1f}s | "
                    f"{state.current_phase:>5} | "
                    f"{metrics.active_vehicles:>10} | "
                    f"{state.total_halting:>10} | "
                    f"{metrics.total_arrived:>10} | "
                    f"{metrics.average_speed_kmh:>14.1f} | "
                    f"{metrics.accumulated_waiting_s:>14.1f}"
                )

        final_metrics = sim.get_metrics()

    real_duration = time.time() - start_real_time
    print(divider)
    print("\n[OK] Simulation Completed Successfully!")
    print(f"  * Real time elapsed   : {real_duration:.2f} s ({duration_s / real_duration:.1f}x real-time speed)")
    print(f"  * Total vehicles sent : {final_metrics.total_departed}")
    print(f"  * Total throughput    : {final_metrics.total_arrived} vehicles arrived")
    print(f"  * Cumulative waiting  : {final_metrics.accumulated_waiting_s:.1f} vehicle-seconds")
    print(f"  * Network average spd : {final_metrics.average_speed_kmh:.1f} km/h")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ResiLight Phase 1 Benchmark Demo")
    parser.add_argument("--duration", type=int, default=120, help="Simulation duration in seconds")
    parser.add_argument("--gui", action="store_true", help="Launch with SUMO-GUI")
    parser.add_argument("--main-vph", type=float, default=800.0, help="Arterial volume (veh/hour)")
    parser.add_argument("--side-vph", type=float, default=450.0, help="Side-street volume (veh/hour)")
    args = parser.parse_args()

    run_demo(
        duration_s=args.duration,
        gui=args.gui,
        main_vph=args.main_vph,
        side_vph=args.side_vph,
    )
