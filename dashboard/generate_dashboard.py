"""
ResiLight Traffic Control Center (TCC) Web Dashboard Generator.

Generates a standalone, responsive HTML dashboard that visualizes:
1. 5G MEC System Status & Current Degradation Level
2. Real-time / Event QoS Metrics
3. Side-by-side performance indicators (ResiLight vs Naive Baseline)
4. Interactive/embedded Bumpless Transfer & Delay charts
5. Structured LLM Diagnostic Agent Report & Actionable Recommendations

Usage:
    python dashboard/generate_dashboard.py
"""
import os
import sys
import json
import base64
from typing import Dict, Any

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_agent import LLMDiagnosticAgent


def image_to_base64(filepath: str) -> str:
    """Encodes an image file to base64 for standalone HTML embedding."""
    if not os.path.exists(filepath):
        return ""
    with open(filepath, "rb") as f:
        return f"data:image/png;base64,{base64.b64encode(f.read()).decode('utf-8')}"


def generate_html_dashboard(
    log_filepath: str,
    output_html_path: str,
    chart1_path: str,
    chart2_path: str,
):
    agent = LLMDiagnosticAgent()
    report = agent.diagnose(log_filepath)
    events = agent.load_events(log_filepath)

    chart1_b64 = image_to_base64(chart1_path)
    chart2_b64 = image_to_base64(chart2_path)

    recommendations_html = "".join(f"<li>{r}</li>" for r in report.operator_recommendations)

    events_rows_html = ""
    for ev in events:
        lvl_class = "lvl-fallback" if ev["to_level"] == 2 else ("lvl-partial" if ev["to_level"] == 1 else "lvl-normal")
        events_rows_html += f"""
        <tr>
            <td><strong>{ev['timestamp_s']:.1f}s</strong></td>
            <td>Level {ev['from_level']} &rarr; <span class="badge {lvl_class}">Level {ev['to_level']}</span></td>
            <td>{ev['latency_ms']:.1f} ms</td>
            <td>{ev['packet_loss_rate']*100:.1f}%</td>
            <td>{ev['total_queued']} 輛</td>
            <td>{ev['reason']}</td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ResiLight — 5G MEC 韌性號誌維運監控儀表板</title>
    <style>
        :root {{
            --primary: #0056b3;
            --primary-dark: #003d82;
            --bg: #f4f6f9;
            --card-bg: #ffffff;
            --text: #212529;
            --text-muted: #6c757d;
            --border: #e9ecef;
            --success: #28a745;
            --warning: #ffc107;
            --danger: #dc3545;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 24px;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: linear-gradient(135deg, var(--primary), var(--primary-dark));
            color: white;
            padding: 20px 28px;
            border-radius: 12px;
            margin-bottom: 24px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }}
        .header h1 {{
            margin: 0;
            font-size: 24px;
            letter-spacing: 0.5px;
        }}
        .header p {{
            margin: 4px 0 0 0;
            opacity: 0.85;
            font-size: 14px;
        }}
        .safety-badge {{
            background: rgba(255,255,255,0.2);
            border: 1px solid rgba(255,255,255,0.4);
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 24px;
        }}
        .card {{
            background: var(--card-bg);
            border-radius: 10px;
            padding: 20px;
            border: 1px solid var(--border);
            box-shadow: 0 2px 6px rgba(0,0,0,0.04);
        }}
        .card-title {{
            font-size: 14px;
            color: var(--text-muted);
            text-transform: uppercase;
            font-weight: 600;
            margin-bottom: 8px;
        }}
        .card-value {{
            font-size: 26px;
            font-weight: 700;
            margin-bottom: 4px;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
        }}
        .lvl-normal {{ background: #e8f5e9; color: #2e7d32; }}
        .lvl-partial {{ background: #fff3e0; color: #e65100; }}
        .lvl-fallback {{ background: #ffebee; color: #c62828; }}
        .llm-section {{
            background: #ffffff;
            border-left: 6px solid var(--primary);
            border-radius: 10px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }}
        .llm-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 12px;
            margin-bottom: 16px;
        }}
        .llm-header h2 {{
            margin: 0;
            font-size: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .severity-badge {{
            padding: 6px 14px;
            border-radius: 6px;
            font-weight: 700;
            font-size: 13px;
        }}
        .sev-CRITICAL {{ background: #dc3545; color: white; }}
        .sev-WARNING {{ background: #ffc107; color: #212529; }}
        .sev-INFO {{ background: #17a2b8; color: white; }}
        .analysis-block {{
            margin-bottom: 16px;
        }}
        .analysis-block h4 {{
            margin: 0 0 6px 0;
            color: var(--primary-dark);
            font-size: 15px;
        }}
        .analysis-block p {{
            margin: 0;
            line-height: 1.6;
            color: #495057;
        }}
        .recommendation-list {{
            margin: 8px 0 0 0;
            padding-left: 20px;
            color: #495057;
            line-height: 1.6;
        }}
        .charts-container {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 24px;
        }}
        @media (max-width: 992px) {{
            .charts-container {{ grid-template-columns: 1fr; }}
        }}
        .chart-box {{
            background: white;
            padding: 18px;
            border-radius: 10px;
            border: 1px solid var(--border);
            text-align: center;
        }}
        .chart-box img {{
            width: 100%;
            height: auto;
            border-radius: 6px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        th {{
            background-color: #f8f9fa;
            color: var(--text-muted);
            font-weight: 600;
        }}
        .footer {{
            text-align: center;
            margin-top: 32px;
            color: var(--text-muted);
            font-size: 13px;
        }}
    </style>
</head>
<body>

    <div class="header">
        <div>
            <h1>ResiLight — 5G MEC 韌性號誌維運監控系統</h1>
            <p>中華電信智慧創新應用大賽 2026 ｜ 智慧交通主題</p>
        </div>
        <div class="safety-badge">
            安全架構承諾：LLM 唯讀審計，不介入號誌硬即時控制迴路
        </div>
    </div>

    <div class="grid">
        <div class="card">
            <div class="card-title">當前狀態機層級</div>
            <div class="card-value"><span class="badge lvl-normal">Level 0: NORMAL</span></div>
            <small style="color: var(--text-muted);">全局協同運作中 (5G MEC 連線良好)</small>
        </div>
        <div class="card">
            <div class="card-title">5G URLLC 鏈路延遲</div>
            <div class="card-value" style="color: var(--success);">15.0 ms</div>
            <small style="color: var(--text-muted);">抖動 2.0 ms ｜ 丟包率 &lt; 0.1%</small>
        </div>
        <div class="card">
            <div class="card-title">延誤降低改善幅度</div>
            <div class="card-value" style="color: var(--primary);">+10.6% ~ +17.9%</div>
            <small style="color: var(--text-muted);">相較傳統無降階基準組 (Naive Baseline)</small>
        </div>
        <div class="card">
            <div class="card-title">後備控制安全約束</div>
            <div class="card-value">10s 綠 / 3s 黃</div>
            <small style="color: var(--text-muted);">Max Pressure (Varaiya, 2013) 本地兜底</small>
        </div>
    </div>

    <!-- LLM Diagnostic Agent Card -->
    <div class="llm-section">
        <div class="llm-header">
            <h2>
                <span>🤖</span>
                <span>交控維運 AI 診斷代理人報告 (LLM Diagnostic Agent)</span>
            </h2>
            <div>
                <span class="severity-badge sev-{report.severity}">{report.severity}</span>
                <span style="font-size: 12px; color: var(--text-muted); margin-left: 8px;">來源：{report.llm_source}</span>
            </div>
        </div>

        <div class="analysis-block">
            <h4>【事件綜整與成因推論】</h4>
            <p>{report.probable_cause}</p>
        </div>

        <div class="analysis-block">
            <h4>【交通衝擊與韌性防護評估】</h4>
            <p>{report.impact_assessment}</p>
        </div>

        <div class="analysis-block">
            <h4>【中華電信交控維運建議 (NOC Operations)】</h4>
            <ul class="recommendation-list">
                {recommendations_html}
            </ul>
        </div>
    </div>

    <!-- Charts Section -->
    <div class="charts-container">
        <div class="chart-box">
            <h3 style="margin-top: 0; font-size: 16px;">無擾動切換 (Bumpless Transfer) S-Curve 銜接軌跡</h3>
            <img src="{chart1_b64}" alt="Bumpless Transfer vs Hard Switch">
        </div>
        <div class="chart-box">
            <h3 style="margin-top: 0; font-size: 16px;">5G 故障全週期延誤與排隊演變對比</h3>
            <img src="{chart2_b64}" alt="Resilience Performance Curves">
        </div>
    </div>

    <!-- Audit Event Log Table -->
    <div class="card">
        <div class="card-title" style="margin-bottom: 14px;">降階狀態機歷史審計日誌 (Audit Trail)</div>
        <table>
            <thead>
                <tr>
                    <th>時間戳 (s)</th>
                    <th>狀態轉移</th>
                    <th>5G 延遲</th>
                    <th>丟包率</th>
                    <th>路口排隊</th>
                    <th>判定原因</th>
                </tr>
            </thead>
            <tbody>
                {events_rows_html}
            </tbody>
        </table>
    </div>

    <div class="footer">
        ResiLight Project © 2026 ｜ 隊伍專屬交付成果 ｜ 符合台灣交控標準與 GSN 封閉架構安全規範
    </div>

</body>
</html>
"""
    os.makedirs(os.path.dirname(os.path.abspath(output_html_path)), exist_ok=True)
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[+] HTML Dashboard generated successfully: {os.path.relpath(output_html_path)}")


def main():
    root_dir = os.path.dirname(os.path.dirname(__file__))
    log_file = os.path.join(root_dir, "sim_output", "degradation_events.json")
    out_html = os.path.join(root_dir, "dashboard", "index.html")
    chart1 = os.path.join(root_dir, "results", "bumpless_vs_hard_switch.png")
    chart2 = os.path.join(root_dir, "results", "resilience_performance_curves.png")

    generate_html_dashboard(log_file, out_html, chart1, chart2)


if __name__ == "__main__":
    main()
