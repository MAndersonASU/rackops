"""Healthy-run calibration for the recovery latency criterion."""

import json
import math
from datetime import UTC, datetime
from pathlib import Path

from rackops import lab

MIN_RUNS = 3
MAX_RUNS = 10
LATENCY_FLOOR_MS = 50.0
HEADROOM_MULTIPLIER = 2.0


def recommend(checks: list[dict]) -> dict:
    if not MIN_RUNS <= len(checks) <= MAX_RUNS:
        raise ValueError(f"Calibration requires {MIN_RUNS}..{MAX_RUNS} healthy runs")
    p95_values = []
    for check in checks:
        p95 = check.get("p95_latency_ms")
        if (
            check.get("passed") is not True
            or check.get("complete_window") is not True
            or check.get("requested_duration_seconds") != 60
            or check.get("requested_rate") != 5
            or type(p95) not in {int, float}
            or not math.isfinite(p95)
            or p95 <= 0
        ):
            raise ValueError("Calibration contains an invalid healthy request window")
        p95_values.append(float(p95))
    maximum = max(p95_values)
    limit = max(LATENCY_FLOOR_MS, math.ceil(maximum * HEADROOM_MULTIPLIER))
    return {
        "criterion_version": "rackops-recovery-v1-candidate",
        "status": "candidate_unfrozen",
        "duration_seconds": 60,
        "requests_per_second": 5,
        "minimum_success_rate": 0.99,
        "latency_statistic": "p95",
        "latency_limit_ms": float(limit),
        "latency_floor_ms": LATENCY_FLOOR_MS,
        "headroom_multiplier": HEADROOM_MULTIPLIER,
        "healthy_runs": len(checks),
        "healthy_p95_latency_ms": p95_values,
        "maximum_healthy_p95_latency_ms": maximum,
    }


def run(record_path: Path, runs: int = MIN_RUNS) -> dict:
    if type(runs) is not int or not MIN_RUNS <= runs <= MAX_RUNS:
        raise ValueError(f"Calibration runs must be {MIN_RUNS}..{MAX_RUNS}")
    checks = []
    initial = lab.run("reset")
    if not initial.get("passed"):
        raise RuntimeError("Calibration baseline reset failed")
    try:
        for _ in range(runs):
            checks.append(
                lab.request_check(
                    duration_seconds=60,
                    latency_limit_ms=500.0,
                    criterion="calibration_input_v1",
                )
            )
        candidate = recommend(checks)
    finally:
        final = lab.run("reset")
        if not final.get("passed"):
            raise RuntimeError("Calibration final reset failed")
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "execution_mode": "kubernetes_calibration",
        "benchmark_eligible": False,
        "candidate": candidate,
        "checks": checks,
    }
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "execution_mode": "kubernetes_calibration",
        "benchmark_eligible": False,
        "passed": True,
        "candidate": candidate,
        "records": str(record_path),
        "next_step": "Review the healthy runs, then freeze a versioned criterion before holdout",
    }
