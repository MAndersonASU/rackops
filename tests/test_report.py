import json

import pytest

from rackops.report import generate


def test_dashboard_labels_replay_and_escapes_selected_content(tmp_path):
    records = tmp_path / "results"
    records.mkdir()
    (records / "selected.json").write_text(
        json.dumps(
            {
                "execution_mode": "fixture",
                "benchmark_eligible": False,
                "scenario": "<script>alert(1)</script>",
                "healthy": {"requests": 2, "successes": 2},
                "fault": {"requests": 2, "successes": 0},
                "recovered": {"requests": 2, "successes": 2},
                "source_run": "javascript:alert(1)",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "dashboard" / "index.html"
    result = generate(records, output)
    page = output.read_text(encoding="utf-8")
    assert result["execution_mode"] == "replay"
    assert "&lt;script&gt;" in page
    assert "<script>alert(1)</script>" not in page
    assert 'href="javascript:' not in page
    assert "0</strong>benchmark-eligible records" in page
    assert "2/2" in page and "0/2" in page


def test_dashboard_rejects_unlabeled_evidence(tmp_path):
    (tmp_path / "bad.json").write_text(json.dumps({"execution_mode": "fixture"}), encoding="utf-8")
    with pytest.raises(ValueError, match="eligibility"):
        generate(tmp_path, tmp_path / "dashboard.html")


def test_dashboard_summarizes_frozen_holdout(tmp_path):
    record = {
        "execution_mode": "kubernetes_holdout",
        "benchmark_eligible": True,
        "completed_attempts": 60,
        "scheduled_attempts": 60,
        "api_cost_usd": 0.130076,
        "by_strategy": {
            name: {
                "healthy_correct": 4,
                "healthy_attempts": 4,
                "unsupported_correct": 4,
                "unsupported_attempts": 4,
                "verified_repair_successes": 12,
                "repairable_attempts": 12,
            }
            for name in ("runbook", "basic", "structured")
        },
    }
    (tmp_path / "holdout.json").write_text(json.dumps(record), encoding="utf-8")
    output = tmp_path / "dashboard.html"
    generate(tmp_path, output)
    page = output.read_text(encoding="utf-8")
    assert "12/12" in page and "36/36" in page
    assert "60/60 attempts passed; $0.130076 API cost" in page
