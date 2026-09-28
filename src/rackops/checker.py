"""Independent request checker; never consumes an agent's success narrative."""

import math
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Protocol

import httpx


class Client(Protocol):
    def request(self, method: str, url: str, **kwargs): ...


@dataclass(frozen=True)
class Sample:
    success: bool
    latency_ms: float
    reason: str


def request_pair(client: Client, key: str, value: str) -> list[Sample]:
    """Validate both HTTP status and exact response body, even after a failed PUT."""
    samples = []
    for method in ("PUT", "GET"):
        samples.append(check_request(client, method, key, value))
    return samples


def check_request(client: Client, method: str, key: str, value: str) -> Sample:
    started = time.perf_counter()
    try:
        kwargs = {"json": {"value": value}} if method == "PUT" else {}
        response = client.request(method, f"/items/{key}", **kwargs)
        if response.status_code != 200:
            success, reason = False, f"http_status_{response.status_code}"
        else:
            success = response.json() == {"key": key, "value": value}
            reason = "correct_response" if success else "incorrect_body"
    except (httpx.HTTPError, ValueError):
        success, reason = False, "transport_or_invalid_json"
    return Sample(success, (time.perf_counter() - started) * 1000, reason)


def summarize(samples: list[Sample], latency_limit_ms: float = 500) -> dict:
    if not math.isfinite(latency_limit_ms) or latency_limit_ms <= 0:
        raise ValueError("Latency threshold must be finite and positive")
    if any(not math.isfinite(s.latency_ms) or s.latency_ms < 0 for s in samples):
        raise ValueError("Invalid observed latency")
    count = len(samples)
    successes = sum(s.success for s in samples)
    p95 = sorted(s.latency_ms for s in samples)[math.ceil(count * 0.95) - 1] if count else None
    return {
        "requests": count,
        "successes": successes,
        "success_rate": successes / count if count else 0,
        "p95_latency_ms": round(p95, 3) if p95 is not None else None,
        "latency_limit_ms": latency_limit_ms,
        "passed": bool(count and successes / count >= 0.99 and p95 <= latency_limit_ms),
    }


def probe(
    client: Client,
    duration: float = 60,
    rate: int = 5,
    latency_limit_ms: float = 500,
    criterion: str = "pilot_unfrozen",
) -> dict:
    if (
        not math.isfinite(duration)
        or not 1 <= duration <= 120
        or not 1 <= rate <= 20
        or type(criterion) is not str
        or not 1 <= len(criterion) <= 64
    ):
        raise ValueError("Probe duration must be 1..120 seconds and rate 1..20 requests/second")
    total = int(duration * rate)
    if total % 2:
        total -= 1
    if total < 2:
        raise ValueError("Probe window must allow a complete write/read pair")
    samples = []
    run_id = uuid.uuid4().hex[:12]
    start = time.monotonic()
    next_due = start
    for index in range(total):
        # Do not send catch-up bursts after slow requests; incomplete windows fail.
        if max(time.monotonic(), next_due) - start >= duration:
            break
        time.sleep(max(0, next_due - time.monotonic()))
        next_due = time.monotonic() + 1 / rate
        key = f"probe-{run_id}-{index // 2}"
        samples.append(check_request(client, "PUT" if index % 2 == 0 else "GET", key, key))
    time.sleep(max(0, start + duration - time.monotonic()))
    result = summarize(samples, latency_limit_ms)
    result.update(
        {
            "duration_seconds": round(time.monotonic() - start, 3),
            "requested_duration_seconds": duration,
            "requested_rate": rate,
            "complete_window": len(samples) == total,
            "criterion": criterion,
        }
    )
    result["passed"] = result["passed"] and result["complete_window"]
    return result


def samples_as_dict(samples: list[Sample]) -> list[dict]:
    return [asdict(sample) for sample in samples]
