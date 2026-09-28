import json

import httpx
import pytest

from rackops.gateway import Evidence, PolicyDenied
from rackops.openai_provider import (
    OpenAIProvider,
    OpenAIProviderError,
    Pricing,
    SpendingBudget,
)
from rackops.runbook import Observations


def observed():
    return Observations(
        False,
        False,
        1,
        8000,
        8000,
        "redis-invalid",
        ("redis",),
        "rackops-api:dev",
        (),
        ("E0001", "E0002"),
    )


def response(intent=None, *, status="completed", input_tokens=100, output_tokens=50):
    intent = intent or {
        "choice": "repair",
        "root_cause": "bad_dependency_configuration",
        "decision": "Restore the observed prior Redis host",
        "kind": "deployment",
        "field": "redis_host",
        "value": "redis",
        "evidence_ids": ["E0001", "E0002"],
    }
    return {
        "id": "resp_fixture",
        "status": status,
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(intent)}],
            }
        ],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def provider(handler, *, cap=1.0, max_attempts=1):
    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://api.openai.com/v1"
    )
    budget = SpendingBudget(cap)
    return (
        OpenAIProvider(
            model_id="fixture-model",
            api_key="fixture-secret",
            pricing=Pricing(1.0, 2.0),
            budget=budget,
            client=client,
            max_attempts=max_attempts,
        ),
        budget,
        client,
    )


def test_structured_response_builds_bounded_nonstored_request_and_tracks_usage():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response())

    hosted, budget, client = provider(handler)
    try:
        intent = hosted.choose(
            observed(),
            (
                Evidence("E0001", "2026-01-01T00:00:00Z", "probe", "write failed"),
                Evidence("E0002", "2026-01-01T00:00:01Z", "deployment", "prior host redis"),
            ),
        )
    finally:
        client.close()
    assert intent.value == "redis"
    assert intent.evidence_ids == ("E0001", "E0002")
    assert hosted.last_usage == {
        "input_tokens": 100,
        "output_tokens": 50,
        "api_cost_usd": 0.0002,
        "budget_charge_usd": 0.0002,
        "api_cost_complete": True,
    }
    assert budget.spent_usd == pytest.approx(0.0002)
    assert budget.reserved_usd == pytest.approx(0)
    assert requests[0].url == "https://api.openai.com/v1/responses"
    payload = json.loads(requests[0].content)
    assert payload["store"] is False
    assert payload["model"] == "fixture-model"
    assert payload["reasoning"] == {"effort": "none"}
    assert payload["text"]["format"]["strict"] is True
    assert "ground_truth" not in payload["input"]


def test_cap_is_reserved_before_network_call():
    calls = []
    hosted, budget, client = provider(lambda request: calls.append(request), cap=0.000001)
    try:
        with pytest.raises(PolicyDenied, match="spending cap"):
            hosted.choose(observed())
    finally:
        client.close()
    assert calls == []
    assert budget.spent_usd == 0
    assert budget.reserved_usd == 0


def test_transient_failure_retries_once_and_charges_unknown_attempt(monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(503, text="private upstream detail")
        return httpx.Response(200, json=response())

    monkeypatch.setattr("rackops.openai_provider.time.sleep", lambda *_: None)
    hosted, budget, client = provider(handler, max_attempts=2)
    try:
        assert hosted.choose(observed()).choice == "repair"
    finally:
        client.close()
    assert len(attempts) == 2
    assert budget.spent_usd > 0.0002
    assert hosted.last_usage["api_cost_usd"] == 0.0002
    assert hosted.last_usage["budget_charge_usd"] > 0.0002
    assert hosted.last_usage["api_cost_complete"] is False


@pytest.mark.parametrize(
    "body,error",
    [
        (response(status="incomplete"), "incomplete"),
        (
            {
                **response(),
                "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
            },
            "refused",
        ),
        ({**response(), "usage": {}}, "token usage"),
    ],
)
def test_incomplete_refusal_and_missing_usage_are_rejected(body, error):
    hosted, budget, client = provider(lambda request: httpx.Response(200, json=body))
    try:
        with pytest.raises(OpenAIProviderError, match=error):
            hosted.choose(observed())
    finally:
        client.close()
    assert budget.reserved_usd == pytest.approx(0)
    if error == "token usage":
        assert budget.spent_usd > 0


def test_nonrepair_cannot_smuggle_mutation_fields():
    body = response(
        {
            "choice": "healthy",
            "root_cause": "healthy",
            "decision": "No action",
            "kind": "deployment",
            "field": "image",
            "value": "rackops-api:other",
            "evidence_ids": ["E0001"],
        }
    )
    hosted, budget, client = provider(lambda request: httpx.Response(200, json=body))
    try:
        with pytest.raises(OpenAIProviderError, match="non-repair"):
            hosted.choose(observed())
    finally:
        client.close()
    assert budget.spent_usd > 0


def test_environment_factory_requires_explicit_owner_configuration():
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIProvider.from_env({})


def test_environment_factory_parses_model_prices_and_smaller_runner_cap():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response())),
        base_url="https://api.openai.com/v1",
    )
    hosted = OpenAIProvider.from_env(
        {
            "OPENAI_API_KEY": "fixture-secret",
            "RACKOPS_LLM_MODEL": "owner-model",
            "RACKOPS_LLM_REASONING_EFFORT": "low",
            "RACKOPS_LLM_BUDGET_USD": "5.0",
            "RACKOPS_LLM_INPUT_USD_PER_MILLION": "1.25",
            "RACKOPS_LLM_OUTPUT_USD_PER_MILLION": "2.5",
            "RACKOPS_LLM_MAX_ATTEMPTS": "1",
        },
        cap_usd=0.75,
        client=client,
    )
    try:
        assert hosted.model_id == "owner-model"
        assert hosted.budget.cap_usd == 0.75
        assert hosted.max_attempts == 1
        assert hosted.reasoning_effort == "low"
    finally:
        client.close()


def test_usage_above_reservation_is_recorded_before_stopping():
    hosted, budget, client = provider(
        lambda request: httpx.Response(
            200,
            json=response(input_tokens=10_000_000, output_tokens=1_000_000),
        )
    )
    try:
        with pytest.raises(OpenAIProviderError, match="exceeded"):
            hosted.choose(observed())
    finally:
        client.close()
    assert budget.reserved_usd == pytest.approx(0)
    assert budget.spent_usd == pytest.approx(12)
