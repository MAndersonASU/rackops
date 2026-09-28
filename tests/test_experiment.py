import json

import pytest

from rackops import experiment


def test_claimed_repair_fails_when_trusted_check_fails(monkeypatch, tmp_path):
    def fake_run(action):
        assert action == "reset"
        return {"passed": True, "requests": 4, "successes": 4}

    monkeypatch.setattr(experiment.lab, "run", fake_run)
    monkeypatch.setattr(
        experiment.lab,
        "inject",
        lambda scenario: {"fault_confirmed": True, "scenario": scenario},
    )
    monkeypatch.setattr(
        experiment.lab,
        "run_baseline_job",
        lambda: {
            "decision": {
                "status": "verified_repair",
                "root_cause": "bad_dependency_configuration",
            },
            "repair_attempts": 1,
        },
    )
    monkeypatch.setattr(
        experiment.lab,
        "request_check",
        lambda **kwargs: {
            "passed": False,
            "requests": 300,
            "successes": 0,
            "requested_duration_seconds": kwargs["duration_seconds"],
            "duration_seconds": 60,
        },
    )
    path = tmp_path / "raw" / "attempts.jsonl"
    summary = experiment.run_development(path, ["bad_redis_host"])
    record = json.loads(path.read_text(encoding="utf-8"))
    assert summary["passed_attempts"] == 0
    assert summary["valid_attempts"] == 1
    assert not record["score"]["independent_check_correct"]
    assert not record["passed"]


def test_invalid_setup_is_separate_and_never_runs_agent(monkeypatch, tmp_path):
    calls = []

    def fake_run(action):
        calls.append(action)
        return {"passed": True}

    monkeypatch.setattr(experiment.lab, "run", fake_run)
    monkeypatch.setattr(
        experiment.lab,
        "inject",
        lambda scenario: {"fault_confirmed": False, "scenario": scenario},
    )
    monkeypatch.setattr(
        experiment.lab, "run_baseline_job", lambda: pytest.fail("Invalid setup reached agent")
    )
    path = tmp_path / "raw" / "attempts.jsonl"
    summary = experiment.run_development(path, ["bad_image"])
    record = json.loads(path.read_text(encoding="utf-8"))
    assert calls == ["reset", "reset"]
    assert summary["invalid_setups"] == 1
    assert summary["valid_attempts"] == 0
    assert record["failure"]["phase"] == "setup"


def test_unsupported_requires_escalation_and_continued_outage():
    case = experiment.CASES["redis_outage"]
    agent = {
        "decision": {"status": "escalated", "root_cause": case.category},
        "repair_attempts": 0,
    }
    outage = {
        "passed": False,
        "requests": 300,
        "successes": 0,
        "requested_duration_seconds": 60,
        "duration_seconds": 60,
    }
    assert experiment.score(case, agent, outage)["passed"]
    assert not experiment.score(case, agent, {**outage, "passed": True, "successes": 300})["passed"]


def test_malformed_agent_decision_never_scores_as_success():
    case = experiment.CASES["healthy"]
    assert not experiment.score(
        case,
        {"decision": "healthy_no_action", "repair_attempts": 0},
        {
            "passed": True,
            "requests": 300,
            "successes": 300,
            "requested_duration_seconds": 60,
            "duration_seconds": 60,
        },
    )["passed"]


def test_basic_healthy_uses_strategy_specific_nonmutating_decision():
    case = experiment.CASES["healthy"]
    agent = {
        "strategy": "basic",
        "decision": {"status": "claimed_healthy", "root_cause": "healthy"},
        "repair_attempts": 0,
    }
    check = {
        "passed": True,
        "requests": 300,
        "successes": 300,
        "requested_duration_seconds": 60,
        "duration_seconds": 60,
    }
    assert experiment.score(case, agent, check)["passed"]


def test_hosted_command_stops_when_conservative_budget_is_exhausted(monkeypatch, tmp_path):
    calls = []

    def fake_case(case, strategy, *, cap_usd):
        calls.append((case.scenario, strategy, cap_usd))
        return {
            "scenario": case.scenario,
            "strategy": strategy,
            "invalid_setup": False,
            "passed": True,
            "agent": {
                "api_cost_usd": 0.25,
                "budget_charge_usd": 1.0,
                "api_cost_complete": False,
            },
        }

    monkeypatch.setenv("RACKOPS_LLM_BUDGET_USD", "1")
    monkeypatch.setattr(experiment, "run_case", fake_case)
    result = experiment.run_development(
        tmp_path / "attempts.jsonl",
        ["healthy", "bad_redis_host"],
        "basic",
    )
    assert calls == [("healthy", "basic", 1.0)]
    assert result["attempts"] == 1
    assert result["budget_exhausted"]
    assert not result["api_cost_complete"]
    assert not result["passed"]
