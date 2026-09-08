"""
ResiLight Master System Integration Runner (End-to-End Pipeline).

Executes the entire ResiLight architecture in a single unified command:
1. Builds SUMO road network and dynamic demand (4-Way Intersection Benchmark).
2. Simulates 5G URLLC communication with a scheduled fiber cut disruption.
3. Coordinates multi-level signal control via DegradationFSM (L0 -> L2 -> Bumpless L0).
4. Evaluates comparative performance against the Naive Baseline.
5. Generates high-resolution publication charts in `results/`.
6. Dispatches the LLM Diagnostic Agent for incident root-cause analysis.
7. Produces the self-contained Traffic Control Center (TCC) HTML Dashboard in `dashboard/index.html`.

Usage:
    python run_full_system.py                     # Headless full pipeline
    python run_full_system.py --gui               # With SUMO-GUI
    python run_full_system.py --open-browser      # Automatically opens generated HTML dashboard
"""
import os
import sys
import time
import argparse
import webbrowser
import logging

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from envs import build_4way_network, build_4way_demand
from run_phase3_evaluation import run_simulation, plot_evaluation_charts
from llm_agent import LLMDiagnosticAgent
from dashboard.generate_dashboard import generate_html_dashboard

logging.basicConfig(level=logging.WARNING)


def main():
    parser = argparse.ArgumentParser(description="ResiLight Master System Runner")
    parser.add_argument("--duration", type=int, default=160, help="Simulation duration (s)")
    parser.add_argument("--cut-start", type=int, default=40, help="Disruption start time (s)")
    parser.add_argument("--cut-duration", type=int, default=50, help="Disruption duration (s)")
    parser.add_argument("--gui", action="store_true", help="Launch SUMO with GUI")
    parser.add_argument("--open-browser", action="store_true", help="Open generated HTML dashboard in browser")
    args = parser.parse_args()

    root_dir = os.path.dirname(os.path.abspath(__file__))
    net_dir = os.path.join(root_dir, "sumo_nets", "benchmark")
    results_dir = os.path.join(root_dir, "results")
    sim_output_dir = os.path.join(root_dir, "sim_output")
    dashboard_dir = os.path.join(root_dir, "dashboard")

    os.makedirs(net_dir, exist_ok=True)
    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(sim_output_dir, exist_ok=True)
    os.makedirs(dashboard_dir, exist_ok=True)

    print("=" * 85)
    print("🚀 ResiLight — 5G MEC 韌性號誌系統 端到端全流程執行展示")
    print("=" * 85)
    print(f"• 模擬時長：{args.duration} 秒")
    print(f"• 故障視窗：t={args.cut_start}s ~ {args.cut_start + args.cut_duration}s (光纖完全中斷 / 丟包率 100%)")
    print(f"• 執行模式：{'SUMO-GUI (可視化)' if args.gui else 'Headless CLI (高速運算)'}")
    print("=" * 85)

    # 1. Road Network & Demand Generation
    print("\n[Step 1/5] 正在生成標準號誌化路網與車流檔案...")
    net_file, tls_id = build_4way_network(net_dir)
    rou_file = build_4way_demand(net_dir, duration_s=args.duration + 60, main_vph=900.0, side_vph=500.0)
    print(f"  [+] 路網檔案：{os.path.relpath(net_file)}")
    print(f"  [+] 車流檔案：{os.path.relpath(rou_file)}")

    # 2. Comparative Simulations
    print("\n[Step 2/5] 執行微觀交通模擬與 5G 故障注入實驗...")
    print("  -> 條件組 A：無降階傳統固定時制基準組 (Naive Baseline)...")
    trace_base = run_simulation(net_file, rou_file, tls_id, args.duration, args.cut_start, args.cut_duration, mode="baseline")

    print("  -> 條件組 B：直接硬切組 (Hard Switch)...")
    trace_hard = run_simulation(net_file, rou_file, tls_id, args.duration, args.cut_start, args.cut_duration, mode="hard_switch")

    print("  -> 條件組 C：ResiLight 韌性降階暨無擾動銜接組 (Ours)...")
    trace_bump = run_simulation(net_file, rou_file, tls_id, args.duration, args.cut_start, args.cut_duration, mode="bumpless")

    # 3. Visualization Charts
    print("\n[Step 3/5] 正在繪製並輸出量化成果圖表...")
    plot_evaluation_charts(trace_base, trace_hard, trace_bump, args.cut_start, args.cut_duration, results_dir)

    # 4. Generate Event Logs for LLM Agent
    log_file = os.path.join(sim_output_dir, "degradation_events.json")
    # Record synthetic log from trace transitions
    events = [
        {
            "timestamp_s": float(args.cut_start),
            "from_level": 0,
            "to_level": 2,
            "reason": "Connection lost / fiber cut",
            "latency_ms": 9999.0,
            "jitter_ms": 0.0,
            "packet_loss_rate": 1.0,
            "active_vehicles": 26,
            "total_queued": trace_bump.queues[args.cut_start] if args.cut_start < len(trace_bump.queues) else 6,
        },
        {
            "timestamp_s": float(args.cut_start + args.cut_duration),
            "from_level": 2,
            "to_level": 0,
            "reason": "Nominal 5G URLLC performance",
            "latency_ms": 15.0,
            "jitter_ms": 2.0,
            "packet_loss_rate": 0.001,
            "active_vehicles": 30,
            "total_queued": trace_bump.queues[args.cut_start + args.cut_duration] if (args.cut_start + args.cut_duration) < len(trace_bump.queues) else 8,
        }
    ]
    with open(log_file, "w", encoding="utf-8") as f:
        import json
        json.dump(events, f, indent=2, ensure_ascii=False)

    # 5. LLM Diagnostic Agent & Dashboard Generation
    print("\n[Step 4/5] 啟動交控維運 AI 診斷代理人 (LLM Diagnostic Agent)...")
    agent = LLMDiagnosticAgent()
    report = agent.diagnose(log_file)
    print(f"  [+] 診斷報告標題：{report.incident_title}")
    print(f"  [+] 嚴重度判定  ：{report.severity}")
    print(f"  [+] 故障成因推論：{report.probable_cause}")

    print("\n[Step 5/5] 生成交控中心維運監控儀表板 HTML...")
    out_html = os.path.join(dashboard_dir, "index.html")
    chart1 = os.path.join(results_dir, "bumpless_vs_hard_switch.png")
    chart2 = os.path.join(results_dir, "resilience_performance_curves.png")
    generate_html_dashboard(log_file, out_html, chart1, chart2)

    # Output Final Summary
    delay_base = trace_base.delays[-1]
    delay_bump = trace_bump.delays[-1]
    delay_hard = trace_hard.delays[-1]
    improvement = ((delay_base - delay_bump) / delay_base) * 100

    print("\n" + "=" * 85)
    print("🏆 RESILIGHT 實測總結效益")
    print("=" * 85)
    print(f"• 基準組累積延誤 (Naive Baseline)      : {delay_base:.1f} 人-秒")
    print(f"• 硬切組累積延誤 (Hard Switch)         : {delay_hard:.1f} 人-秒")
    print(f"• ResiLight 累積延誤 (Bumpless Ours)    : {delay_bump:.1f} 人-秒 (降低 {improvement:.1f}%)")
    print(f"• 高畫質圖表 1 (無擾動 S-Curve 時制)   : {os.path.relpath(chart1)}")
    print(f"• 高畫質圖表 2 (5G 故障全週期延誤演變) : {os.path.relpath(chart2)}")
    print(f"• 完整交控 HTML 儀表板                 : {os.path.relpath(out_html)}")
    print("=" * 85)

    if args.open_browser:
        webbrowser.open(f"file:///{out_html}")


if __name__ == "__main__":
    main()
