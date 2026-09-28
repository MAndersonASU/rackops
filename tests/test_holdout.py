import json
from pathlib import Path

import pytest

from rackops import holdout


def manifest_path():
    return Path(__file__).parents[1] / "evaluation" / "reduced-holdout-v1.json"


def test_frozen_reduced_plan_builds_balanced_randomized_schedule():
    plan = holdout.load_plan(manifest_path())
    schedule = holdout.build_schedule(plan)
    assert len(schedule) == 60
    assert len({item["attempt_id"] for item in schedule}) == 60
    for case in plan["cases"]:
        selected = [item for item in schedule if item["case_id"] == case["id"]]
        assert len(selected) == 6
        assert {item["strategy"] for item in selected} == set(holdout.STRATEGIES)
        assert {item["repetition"] for item in selected} == {1, 2}
    assert schedule == holdout.build_schedule(plan)


def test_manifest_change_is_rejected(tmp_path):
    plan = json.loads(manifest_path().read_text(encoding="utf-8"))
    plan["criterion"]["latency_limit_ms"] = 500.0
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen reduced protocol"):
        holdout.load_plan(changed)


def test_resume_rejects_records_from_another_manifest(tmp_path):
    plan = holdout.load_plan(manifest_path())
    schedule = holdout.build_schedule(plan)
    records = tmp_path / "holdout.jsonl"
    records.write_text(
        json.dumps({"attempt_id": schedule[0]["attempt_id"], "manifest_sha256": "wrong"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="frozen schedule prefix"):
        holdout._existing_records(records, "expected", "provider", "implementation", schedule)


def test_summary_keeps_denominators_and_safety_counts_separate():
    record = {
        "strategy": "runbook",
        "scenario": "bad_redis_host",
        "ground_truth_category": "bad_dependency_configuration",
        "invalid_setup": False,
        "passed": True,
        "score": {"decision_correct": True},
        "agent": {
            "decision": {"root_cause": "bad_dependency_configuration"},
            "elapsed_seconds": 61.5,
            "tool_calls": 8,
            "repair_attempts": 1,
            "attempted_policy_violations": 1,
            "actions": [
                {
                    "kind": "deployment",
                    "name": "rackops-api",
                    "field": "redis_host",
                    "rollback_status": "verified",
                }
            ],
        },
    }
    summary = holdout.summarize([record], [{"attempt_id": "one"}], "manifest", "implementation")
    runbook = summary["by_strategy"]["runbook"]
    assert runbook["repairable_attempts"] == 1
    assert runbook["verified_repair_successes"] == 1
    assert runbook["top1_root_cause_correct"] == 1
    assert runbook["attempted_policy_violations"] == 1
    assert runbook["executed_forbidden_actions"] == 0
    assert runbook["rollback_outcomes"]["verified"] == 1
