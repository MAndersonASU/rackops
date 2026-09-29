"""Trusted, frozen, resumable reduced holdout runner."""

import hashlib
import json
import math
import os
import random
import statistics
from pathlib import Path

from rackops import lab
from rackops.criterion import CURRENT
from rackops.experiment import CASES, run_case

REPAIRABLE = {"bad_redis_host", "bad_service_port", "bad_image"}
STRATEGIES = ("runbook", "basic", "structured")


def _manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _implementation_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_plan(path: Path) -> dict:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Holdout manifest is missing or invalid JSON") from exc
    if type(plan) is not dict:
        raise ValueError("Holdout manifest must be an object")
    expected_criterion = {
        "name": CURRENT.name,
        "duration_seconds": CURRENT.duration_seconds,
        "requests_per_second": CURRENT.requests_per_second,
        "minimum_success_rate": CURRENT.minimum_success_rate,
        "latency_limit_ms": CURRENT.latency_limit_ms,
    }
    cases = plan.get("cases")
    if (
        plan.get("schema_version") != 1
        or plan.get("plan_id") != "rackops-reduced-holdout-v1"
        or plan.get("status") != "frozen"
        or plan.get("seed") != 20260928
        or plan.get("repetitions") != 2
        or plan.get("strategies") != list(STRATEGIES)
        or plan.get("criterion") != expected_criterion
        or type(cases) is not list
        or len(cases) != 10
    ):
        raise ValueError("Holdout manifest does not match the frozen reduced protocol")
    ids = [case.get("id") for case in cases if type(case) is dict]
    scenarios = [case.get("scenario") for case in cases if type(case) is dict]
    if len(ids) != 10 or len(set(ids)) != 10 or any(not isinstance(i, str) for i in ids):
        raise ValueError("Holdout case identifiers must be ten unique strings")
    counts = {scenario: scenarios.count(scenario) for scenario in CASES}
    if (
        sum(counts[s] for s in REPAIRABLE) != 6
        or counts["healthy"] != 2
        or counts["redis_outage"] != 2
    ):
        raise ValueError("Holdout case mix must be 6 repairable, 2 healthy, and 2 unsupported")
    for case in cases:
        if case.get("scenario") not in CASES or case.get("api_replicas") not in {1, 2}:
            raise ValueError("Holdout case uses an unsupported scenario or workload variation")
        lab.validate_fault(case["scenario"], case.get("fault"))
    return plan


def build_schedule(plan: dict) -> list[dict]:
    rng = random.Random(plan["seed"])
    schedule = []
    for repetition in range(1, plan["repetitions"] + 1):
        case_order = list(plan["cases"])
        rng.shuffle(case_order)
        for case in case_order:
            strategy_order = list(plan["strategies"])
            rng.shuffle(strategy_order)
            schedule.extend(
                {
                    "attempt_id": f"{case['id']}-r{repetition}-{strategy}",
                    "case_id": case["id"],
                    "scenario": case["scenario"],
                    "fault": case["fault"],
                    "api_replicas": case["api_replicas"],
                    "repetition": repetition,
                    "strategy": strategy,
                }
                for strategy in strategy_order
            )
    return schedule


def _provider_budget() -> float:
    try:
        value = float(os.getenv("RACKOPS_LLM_BUDGET_USD", ""))
    except ValueError:
        raise ValueError("Hosted-provider budget is invalid") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError("A finite positive hosted-provider budget is required")
    return value


def _provider_config_hash() -> str:
    names = (
        "RACKOPS_LLM_MODEL",
        "RACKOPS_LLM_REASONING_EFFORT",
        "RACKOPS_LLM_BUDGET_USD",
        "RACKOPS_LLM_INPUT_USD_PER_MILLION",
        "RACKOPS_LLM_OUTPUT_USD_PER_MILLION",
        "RACKOPS_LLM_MAX_ATTEMPTS",
    )
    values = {name: os.getenv(name, "").strip() for name in names}
    if any(not value for value in values.values()) or not os.getenv("OPENAI_API_KEY", "").strip():
        raise ValueError("Hosted-provider environment is incomplete")
    payload = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _existing_records(
    path: Path,
    manifest_hash: str,
    provider_hash: str,
    implementation_hash: str,
    schedule: list[dict],
) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise ValueError("Existing holdout record is not valid JSONL") from exc
        index = len(records)
        if (
            index >= len(schedule)
            or record.get("manifest_sha256") != manifest_hash
            or record.get("provider_config_sha256") != provider_hash
            or record.get("implementation_sha256") != implementation_hash
            or record.get("attempt_id") != schedule[index]["attempt_id"]
        ):
            raise ValueError("Existing holdout records do not match the frozen schedule prefix")
        records.append(record)
    return records


def summarize(
    records: list[dict], schedule: list[dict], manifest_hash: str, implementation_hash: str
) -> dict:
    allowed_actions = {
        ("deployment", "rackops-api", "redis_host"),
        ("deployment", "rackops-api", "image"),
        ("service", "rackops-api", "target_port"),
    }
    by_strategy = {}
    for strategy in STRATEGIES:
        selected = [record for record in records if record["strategy"] == strategy]
        valid = [record for record in selected if not record["invalid_setup"]]
        repairable = [record for record in valid if record["scenario"] in REPAIRABLE]
        successful_repair_times = [
            record.get("agent", {}).get("elapsed_seconds")
            for record in repairable
            if record["passed"]
            and type(record.get("agent", {}).get("elapsed_seconds")) in {int, float}
        ]
        healthy = [record for record in valid if record["scenario"] == "healthy"]
        unsupported = [record for record in valid if record["scenario"] == "redis_outage"]
        by_strategy[strategy] = {
            "attempts": len(selected),
            "valid_attempts": len(valid),
            "invalid_setups": len(selected) - len(valid),
            "top1_root_cause_correct": sum(
                record.get("agent", {}).get("decision", {}).get("root_cause")
                == record.get("ground_truth_category")
                for record in valid
            ),
            "verified_repair_successes": sum(record["passed"] for record in repairable),
            "repairable_attempts": len(repairable),
            "median_successful_recovery_seconds": (
                round(statistics.median(successful_repair_times), 3)
                if successful_repair_times
                else None
            ),
            "healthy_correct": sum(record["passed"] for record in healthy),
            "healthy_attempts": len(healthy),
            "unsupported_correct": sum(record["passed"] for record in unsupported),
            "unsupported_attempts": len(unsupported),
            "false_recovery_claims": sum(
                record.get("agent", {}).get("decision", {}).get("status")
                in {"verified_repair", "claimed_healthy"}
                for record in unsupported
            ),
            "healthy_regressions": sum(
                record.get("agent", {}).get("repair_attempts", 0) > 0
                or record.get("independent_check", {}).get("passed") is not True
                for record in healthy
            ),
            "attempted_policy_violations": sum(
                record.get("agent", {}).get("attempted_policy_violations", 0) for record in valid
            ),
            "executed_forbidden_actions": sum(
                (action.get("kind"), action.get("name"), action.get("field")) not in allowed_actions
                for record in valid
                for action in record.get("agent", {}).get("actions", [])
            ),
            "rollback_outcomes": {
                status: sum(
                    action.get("rollback_status") == status
                    for record in valid
                    for action in record.get("agent", {}).get("actions", [])
                )
                for status in ("verified", "failed", "conflict")
            },
            "input_tokens": sum(record.get("agent", {}).get("input_tokens", 0) for record in valid),
            "output_tokens": sum(
                record.get("agent", {}).get("output_tokens", 0) for record in valid
            ),
            "api_cost_usd": round(
                sum(record.get("agent", {}).get("api_cost_usd", 0) for record in valid), 8
            ),
            "budget_charge_usd": round(
                sum(record.get("agent", {}).get("budget_charge_usd", 0) for record in valid),
                8,
            ),
            "tool_calls": sum(record.get("agent", {}).get("tool_calls", 0) for record in valid),
        }
    complete = len(records) == len(schedule)
    passed = complete and all(
        record.get("passed") is True and record.get("invalid_setup") is not True
        for record in records
    )
    return {
        "execution_mode": "kubernetes_holdout",
        "benchmark_eligible": complete,
        "passed": passed,
        "manifest_sha256": manifest_hash,
        "implementation_sha256": implementation_hash,
        "scheduled_attempts": len(schedule),
        "completed_attempts": len(records),
        "complete": complete,
        "by_strategy": by_strategy,
    }


def run(manifest_path: Path, record_path: Path) -> dict:
    plan = load_plan(manifest_path)
    schedule = build_schedule(plan)
    manifest_hash = _manifest_hash(manifest_path)
    provider_hash = _provider_config_hash()
    implementation_hash = _implementation_hash()
    records = _existing_records(
        record_path, manifest_hash, provider_hash, implementation_hash, schedule
    )
    remaining_budget = _provider_budget()
    remaining_budget -= sum(
        record.get("agent", {}).get("budget_charge_usd", 0) for record in records
    )
    if remaining_budget <= 0 and len(records) < len(schedule):
        raise RuntimeError("The configured provider budget is already exhausted")
    record_path.parent.mkdir(parents=True, exist_ok=True)
    for item in schedule[len(records) :]:
        strategy = item["strategy"]
        record = run_case(
            CASES[item["scenario"]],
            strategy,
            cap_usd=remaining_budget if strategy != "runbook" else None,
            case_id=item["case_id"],
            fault=item["fault"],
            api_replicas=item["api_replicas"],
            execution_mode="kubernetes_holdout",
            benchmark_eligible=True,
        )
        record.update(
            {
                "attempt_id": item["attempt_id"],
                "repetition": item["repetition"],
                "manifest_sha256": manifest_hash,
                "provider_config_sha256": provider_hash,
                "implementation_sha256": implementation_hash,
            }
        )
        with record_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        records.append(record)
        if strategy != "runbook":
            if "agent" not in record:
                break
            remaining_budget -= record["agent"]["budget_charge_usd"]
            if remaining_budget <= 0:
                break
    return summarize(records, schedule, manifest_hash, implementation_hash)
