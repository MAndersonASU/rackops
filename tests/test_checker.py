import httpx
import pytest

from rackops.checker import Sample, probe, request_pair, summarize


def test_successful_status_with_wrong_value_is_failed_repair():
    def corrupt(_request):
        return httpx.Response(200, json={"key": "key", "value": "corrupted"})

    with httpx.Client(transport=httpx.MockTransport(corrupt), base_url="http://fixture") as client:
        samples = request_pair(client, "key", "expected")
        result = summarize(samples)
    assert result["successes"] == 0
    assert result["passed"] is False
    assert [sample.reason for sample in samples] == ["incorrect_body", "incorrect_body"]


def test_status_failure_reports_code_without_response_content():
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(503, json={"detail": "private"})),
        base_url="http://fixture",
    ) as client:
        samples = request_pair(client, "key", "value")
    assert [sample.reason for sample in samples] == ["http_status_503", "http_status_503"]


def test_superficial_health_endpoint_cannot_prove_recovery():
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "ok"})),
        base_url="http://fixture",
    ) as client:
        assert not summarize(request_pair(client, "key", "value"))["passed"]


def test_slo_counts_denominator_and_tail_latency():
    samples = [Sample(True, 10, "ok")] * 99 + [Sample(False, 20, "failed")]
    assert summarize(samples)["passed"]
    assert not summarize(samples + [Sample(False, 10, "failed")])["passed"]
    assert not summarize([Sample(True, 501, "slow")])["passed"]
    assert not summarize([])["passed"]


@pytest.mark.parametrize("latency", [float("nan"), float("inf"), -1])
def test_invalid_latency_rejected(latency):
    with pytest.raises(ValueError):
        summarize([Sample(True, latency, "invalid")])


@pytest.mark.parametrize("duration,rate", [(0, 5), (121, 5), (float("nan"), 5), (60, 0), (60, 21)])
def test_unbounded_probe_rejected(duration, rate):
    with pytest.raises(ValueError):
        probe(None, duration=duration, rate=rate)


def test_transport_failure_is_not_success():
    def fail(request):
        raise httpx.ConnectError("fixture refused", request=request)

    with httpx.Client(transport=httpx.MockTransport(fail), base_url="http://fixture") as client:
        assert summarize(request_pair(client, "key", "value"))["successes"] == 0


def test_slow_requests_cannot_pass_an_incomplete_window(monkeypatch):
    from rackops import checker

    now = [0.0]
    starts = []
    monkeypatch.setattr(checker.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(checker.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))

    def slow_request(*args):
        starts.append(now[0])
        now[0] += 0.4
        return Sample(True, 400, "correct_response")

    monkeypatch.setattr(checker, "check_request", slow_request)
    result = probe(None, duration=2, rate=5)
    assert result["success_rate"] == 1
    assert not result["complete_window"]
    assert not result["passed"]
    assert all(b - a >= 0.2 for a, b in zip(starts, starts[1:], strict=False))
