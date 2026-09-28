import pytest

from rackops import calibration


def healthy(p95):
    return {
        "passed": True,
        "complete_window": True,
        "requested_duration_seconds": 60,
        "requested_rate": 5,
        "p95_latency_ms": p95,
    }


def test_recommendation_uses_worst_healthy_p95_headroom_and_floor():
    result = calibration.recommend([healthy(4.2), healthy(11.1), healthy(7.0)])
    assert result["latency_limit_ms"] == 50.0
    assert result["maximum_healthy_p95_latency_ms"] == 11.1
    assert result["status"] == "candidate_unfrozen"

    slower = calibration.recommend([healthy(20), healthy(29.1), healthy(31.2)])
    assert slower["latency_limit_ms"] == 63.0


@pytest.mark.parametrize(
    "checks",
    [
        [healthy(1), healthy(2)],
        [healthy(1), healthy(2), {**healthy(3), "complete_window": False}],
        [healthy(1), healthy(2), {**healthy(3), "passed": False}],
        [healthy(1), healthy(2), {**healthy(3), "p95_latency_ms": float("nan")}],
    ],
)
def test_recommendation_rejects_insufficient_or_invalid_windows(checks):
    with pytest.raises(ValueError):
        calibration.recommend(checks)


def test_live_calibration_writes_raw_candidate_and_resets(monkeypatch, tmp_path):
    resets = []

    def fake_run(action):
        resets.append(action)
        return {"passed": True}

    values = iter([healthy(5), healthy(6), healthy(7)])
    monkeypatch.setattr(calibration.lab, "run", fake_run)
    monkeypatch.setattr(
        calibration.lab,
        "request_check",
        lambda **kwargs: next(values) | {"requested_duration_seconds": kwargs["duration_seconds"]},
    )
    path = tmp_path / "calibration.json"
    result = calibration.run(path, 3)
    assert resets == ["reset", "reset"]
    assert result["candidate"]["healthy_runs"] == 3
    assert result["candidate"]["status"] == "candidate_unfrozen"
    assert path.exists()
