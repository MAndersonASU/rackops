"""In-cluster check that Prometheus exposes a bounded RackOps request rate."""

import json
import math
import time

import httpx

QUERY = 'sum(rate(rackops_http_requests_total{route="/items/{key}"}[1m]))'


def main():
    deadline = time.monotonic() + 30
    with httpx.Client(
        base_url="http://prometheus:9090",
        timeout=2,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get("/api/v1/query", params={"query": QUERY})
                response.raise_for_status()
                body = response.json()
                results = body.get("data", {}).get("result", [])
                value = float(results[0]["value"][1]) if results else 0.0
                if math.isfinite(value) and value > 0:
                    print(
                        json.dumps(
                            {
                                "passed": True,
                                "metric": "rackops_http_requests_total_rate",
                                "value_per_second": round(value, 6),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                    return
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                pass
            time.sleep(2)
    print(
        json.dumps(
            {
                "passed": False,
                "metric": "rackops_http_requests_total_rate",
                "reason": "no_positive_finite_series_within_30_seconds",
            },
            sort_keys=True,
        ),
        flush=True,
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
