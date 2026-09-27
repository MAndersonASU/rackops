"""Explicitly mocked dependency demo. Never used as a real benchmark result."""

from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from rackops.app import create_app
from rackops.checker import request_pair, summarize


def run_demo() -> dict:
    try:
        import fakeredis
    except ImportError as exc:
        raise RuntimeError("Fixture demo requires the development dependencies") from exc

    store = fakeredis.FakeRedis(decode_responses=True)

    class FixtureConnection:
        # Emulate selection of the wrong dependency endpoint, with ordinary config history.
        host = "redis"
        history = ["redis"]

        def __getattr__(self, name):
            if name == "close":
                return lambda: None
            if self.host != "redis":
                raise ConnectionError("Fixture endpoint unavailable")
            return getattr(store, name)

    connection = FixtureConnection()
    try:
        with TestClient(create_app(connection)) as client:
            healthy = summarize(request_pair(client, "demo-healthy", "disposable"))
            connection.host = "redis-invalid"
            faulty = summarize(request_pair(client, "demo-fault", "disposable"))
            alive_during_fault = client.get("/livez").status_code == 200
            ready_during_fault = client.get("/readyz").status_code == 200
            connection.host = connection.history[-1]
            recovered = summarize(request_pair(client, "demo-recovery", "disposable"))
            metrics_visible = "rackops_http_requests_total" in client.get("/metrics").text
    finally:
        store.close()
    return {
        "execution_mode": "fixture",
        "benchmark_eligible": False,
        "scenario": "bad_dependency_configuration",
        "healthy": healthy,
        "fault": faulty,
        "alive_during_fault": alive_during_fault,
        "ready_during_fault": ready_during_fault,
        "repair": "restore fixture connection from configuration history",
        "recovered": recovered,
        "metrics_visible": metrics_visible,
        "passed": healthy["passed"]
        and not faulty["passed"]
        and recovered["passed"]
        and alive_during_fault
        and not ready_during_fault
        and metrics_visible,
    }
