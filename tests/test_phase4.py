"""
Phase 4 Validation Tests: LLM Diagnostic Agent & TCC Web Dashboard.

Validates:
1. Event loading and Traditional Chinese analytical prompt generation
2. Offline Domain-Expert diagnostic engine (severity, cause deduction, impact, recommendations)
3. Empty/nominal state handling
4. Standalone self-contained HTML dashboard generation
"""
import os
import json
import shutil
import tempfile
import pytest

from llm_agent import LLMDiagnosticAgent, DiagnosticReport
from dashboard.generate_dashboard import generate_html_dashboard


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="resilight_phase4_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_llm_agent_load_and_prompt(temp_dir):
    """Verify JSON log loading and prompt construction."""
    log_file = os.path.join(temp_dir, "test_events.json")
    sample_events = [
        {
            "timestamp_s": 30.0,
            "from_level": 0,
            "to_level": 2,
            "reason": "Connection lost / fiber cut",
            "latency_ms": 9999.0,
            "jitter_ms": 0.0,
            "packet_loss_rate": 1.0,
            "active_vehicles": 25,
            "total_queued": 8,
        }
    ]
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(sample_events, f)

    agent = LLMDiagnosticAgent()
    events = agent.load_events(log_file)
    assert len(events) == 1
    assert events[0]["from_level"] == 0
    assert events[0]["to_level"] == 2

    prompt = agent.generate_prompt(events)
    assert "中華電信" in prompt
    assert "ResiLight" in prompt
    assert "Level 2 (FALLBACK)" in prompt
    assert "fiber cut" in prompt


def test_expert_rule_diagnosis_fiber_cut(temp_dir):
    """Verify that severe fiber cut is assessed as CRITICAL with concrete action items."""
    log_file = os.path.join(temp_dir, "test_cut.json")
    sample_events = [
        {
            "timestamp_s": 20.0,
            "from_level": 0,
            "to_level": 2,
            "reason": "Connection lost / fiber cut",
            "latency_ms": 9999.0,
            "jitter_ms": 0.0,
            "packet_loss_rate": 1.0,
            "active_vehicles": 30,
            "total_queued": 9,
        },
        {
            "timestamp_s": 65.0,
            "from_level": 2,
            "to_level": 0,
            "reason": "Nominal 5G URLLC performance",
            "latency_ms": 15.0,
            "jitter_ms": 2.0,
            "packet_loss_rate": 0.001,
            "active_vehicles": 28,
            "total_queued": 5,
        }
    ]
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(sample_events, f)

    agent = LLMDiagnosticAgent()
    report = agent.diagnose(log_file)

    assert isinstance(report, DiagnosticReport)
    assert report.severity == "CRITICAL"
    assert pytest.approx(report.incident_duration_s, abs=1.0) == 45.0
    assert "光纖" in report.probable_cause or "中斷" in report.probable_cause
    assert len(report.operator_recommendations) >= 3
    assert report.llm_source == "Domain-Expert-Fallback"


def test_expert_rule_diagnosis_empty(temp_dir):
    """Verify that empty/nominal event logs produce an INFO report."""
    log_file = os.path.join(temp_dir, "test_empty.json")
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump([], f)

    agent = LLMDiagnosticAgent()
    report = agent.diagnose(log_file)

    assert report.severity == "INFO"
    assert report.incident_duration_s == 0.0


def test_dashboard_html_generation(temp_dir):
    """Verify that generate_html_dashboard creates a complete, valid HTML file."""
    log_file = os.path.join(temp_dir, "test_events.json")
    sample_events = [
        {
            "timestamp_s": 10.0,
            "from_level": 0,
            "to_level": 2,
            "reason": "Connection lost / fiber cut",
            "latency_ms": 9999.0,
            "jitter_ms": 0.0,
            "packet_loss_rate": 1.0,
            "active_vehicles": 15,
            "total_queued": 4,
        }
    ]
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(sample_events, f)

    out_html = os.path.join(temp_dir, "index.html")
    # Empty dummy chart paths
    generate_html_dashboard(log_file, out_html, chart1_path="nonexistent1.png", chart2_path="nonexistent2.png")

    assert os.path.isfile(out_html)
    with open(out_html, "r", encoding="utf-8") as f:
        content = f.read()

    assert "<!DOCTYPE html>" in content
    assert "ResiLight" in content
    assert "LLM Diagnostic Agent" in content
    assert "CRITICAL" in content
    assert "降階狀態機歷史審計日誌" in content
