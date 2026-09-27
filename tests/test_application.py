import fakeredis
import pytest
from fastapi.testclient import TestClient

from rackops.app import create_app
from rackops.checker import request_pair, summarize
from rackops.fixture_demo import run_demo


@pytest.fixture
def app_client():
    server = fakeredis.FakeServer()
    redis = fakeredis.FakeRedis(server=server, decode_responses=True)
    with TestClient(create_app(redis)) as client:
        yield client, server, redis


def test_round_trip_uses_disposable_redis_data(app_client):
    client, _, redis = app_client
    assert summarize(request_pair(client, "smoke", "hello"))["passed"]
    assert redis.get("rackops:smoke") == "hello"
    assert 0 < redis.ttl("rackops:smoke") <= 120
    assert client.get("/items/missing").status_code == 404


def test_outage_does_not_change_process_liveness(app_client):
    client, server, _ = app_client
    server.connected = False
    assert client.get("/livez").status_code == 200
    assert client.get("/readyz").status_code == 503
    assert not summarize(request_pair(client, "down", "hello"))["passed"]
    server.connected = True
    assert summarize(request_pair(client, "up", "hello"))["passed"]


@pytest.mark.parametrize(
    "body",
    [{"value": ""}, {"value": "x" * 1025}, {"value": 1}, {"value": "ok", "unexpected": True}, {}],
)
def test_malformed_inputs_are_rejected(app_client, body):
    client, _, redis = app_client
    assert client.put("/items/key", json=body).status_code == 422
    assert redis.dbsize() == 0


def test_invalid_key_rejected(app_client):
    client, _, _ = app_client
    assert client.put("/items/invalid.key", json={"value": "ok"}).status_code == 422


def test_metrics_use_templates_and_record_failures(app_client):
    client, server, _ = app_client
    client.get("/items/unique_private_key")
    server.connected = False
    client.get("/items/other_private_key")
    metrics = client.get("/metrics").text
    assert 'route="/items/{key}",status="503"' in metrics
    assert "unique_private_key" not in metrics
    assert "other_private_key" not in metrics


def test_fixture_demo_is_labeled_and_proves_fault_then_recovery():
    result = run_demo()
    assert result["passed"]
    assert result["execution_mode"] == "fixture"
    assert result["benchmark_eligible"] is False
    assert result["fault"]["successes"] == 0
    assert result["recovered"]["successes"] == 2
