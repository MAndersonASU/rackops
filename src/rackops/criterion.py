"""Single versioned recovery criterion used by runtime and outer checkers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryCriterion:
    name: str
    duration_seconds: int
    requests_per_second: int
    minimum_success_rate: float
    latency_limit_ms: float
    frozen: bool


# Frozen before holdout from five complete healthy windows in GitHub Actions
# run 36374095023. The predeclared rule was max(50 ms, 2 * worst healthy p95);
# the worst observed p95 was 3.502 ms, so the floor controls.
CURRENT = RecoveryCriterion(
    name="rackops-recovery-v1",
    duration_seconds=60,
    requests_per_second=5,
    minimum_success_rate=0.99,
    latency_limit_ms=50.0,
    frozen=True,
)
