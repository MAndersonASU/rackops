"""Trusted serial development runner; scenario truth never enters the agent Job."""

import json
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rackops import lab
from rackops.criterion import CURRENT


@dataclass(frozen=True)
class Case:
    scenario: str
    category: str
    decision: str
    repairs: int
    application_should_pass: bool


CASES = {
    case.scenario: case
    for case in (
        Case("bad_redis_host", "bad_dependency_configuration", "verified_repair", 1, True),
        Case("bad_service_port", "bad_service_target_port", "verified_repair", 1, True),
        Case("bad_image", "broken_image", "verified_repair", 1, True),
        Case("redis_outage", "unsupported_dependency_outage", "escalated", 0, False),
        Case("healthy", "healthy", "healthy_no_action", 0, True),
    )
}


def score(case: Case, agent_result: dict, independent_check: dict) -> dict:
    """Compare the runtime's decision with hidden truth and a fresh runner check."""
    decision = agent_result.get("decision", {})
    if type(decision) is not dict:
        decision = {}
    strategy = agent_result.get("strategy", "runbook")
    expected_decision = (
        "claimed_healthy" if strategy == "basic" and case.scenario == "healthy" else case.decision
    )
    expected_behavior = (
        decision.get("status") == expected_decision
        and decision.get("root_cause") == case.category
        and agent_result.get("repair_attempts") == case.repairs
    )
    observed_behavior = (
        independent_check.get("passed") is case.application_should_pass
        and CURRENT.frozen
        and independent_check.get("criterion") == CURRENT.name
        and independent_check.get("requested_duration_seconds") == CURRENT.duration_seconds
        and independent_check.get("requested_rate") == CURRENT.requests_per_second
        and independent_check.get("latency_limit_ms") == CURRENT.latency_limit_ms
        and independent_check.get("duration_seconds", 0) >= CURRENT.duration_seconds
        and independent_check.get("requests", 0) > 0
        and (
            independent_check.get("successes", 0) >= 297
            if case.application_should_pass
            else independent_check.get("successes") == 0
        )
    )
    return {
        "expected_decision": expected_decision,
        "expected_category": case.category,
        "expected_repairs": case.repairs,
        "decision_correct": expected_behavior,
        "independent_check_correct": observed_behavior,
        "passed": expected_behavior and observed_behavior,
    }


def run_case(case: Case, strategy: str = "runbook", *, cap_usd: float | None = None) -> dict:
    """Reset before and after an attempt, recording invalid setups separately."""
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "execution_mode": "kubernetes_development",
        "benchmark_eligible": False,
        "strategy": strategy,
        "scenario": case.scenario,
        "ground_truth_category": case.category,
        "invalid_setup": False,
        "passed": False,
    }
    try:
        initial = lab.run("reset")
        if not initial.get("passed"):
            raise RuntimeError("Baseline reset did not pass request checks")
        injected = lab.inject(case.scenario)
        if case.scenario == "healthy":
            manifested = injected.get("passed") is True and injected.get("mutation_count") == 0
        else:
            manifested = injected.get("fault_confirmed") is True
        if not manifested:
            raise RuntimeError("Scenario did not manifest")
        record["setup"] = {"baseline": initial, "injection": injected}
    except (RuntimeError, ValueError, OSError) as exc:
        record["invalid_setup"] = True
        record["failure"] = {"phase": "setup", "type": type(exc).__name__}
    else:
        try:
            agent_result = (
                lab.run_baseline_job()
                if strategy == "runbook"
                else lab.run_agent_job(strategy, cap_usd=cap_usd)
            )
            independent_check = lab.request_check(
                duration_seconds=CURRENT.duration_seconds,
                rate=CURRENT.requests_per_second,
                latency_limit_ms=CURRENT.latency_limit_ms,
                criterion=CURRENT.name,
            )
            record["agent"] = agent_result
            record["independent_check"] = independent_check
            record["score"] = score(case, agent_result, independent_check)
            record["passed"] = record["score"]["passed"]
        except (RuntimeError, ValueError, OSError) as exc:
            record["failure"] = {"phase": "execution", "type": type(exc).__name__}
    finally:
        try:
            reset = lab.run("reset")
            record["final_reset"] = reset
            if not reset.get("passed"):
                record["passed"] = False
                record["failure"] = {"phase": "reset", "type": "FailedCheck"}
        except (RuntimeError, ValueError, OSError) as exc:
            record["passed"] = False
            record["failure"] = {"phase": "reset", "type": type(exc).__name__}
    return record


def run_development(
    record_path: Path,
    scenarios: list[str] | None = None,
    strategy: str = "runbook",
) -> dict:
    if strategy not in {"runbook", "basic", "structured"}:
        raise ValueError("Choose runbook, basic, or structured")
    selected = list(CASES) if scenarios is None else scenarios
    if not selected or len(set(selected)) != len(selected) or any(s not in CASES for s in selected):
        raise ValueError("Choose distinct supported development scenarios")
    record_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    configured_budget = None
    remaining_budget = None
    if strategy != "runbook":
        try:
            configured_budget = float(os.getenv("RACKOPS_LLM_BUDGET_USD", ""))
        except ValueError:
            raise ValueError("Hosted-provider budget is invalid") from None
        if not math.isfinite(configured_budget) or configured_budget <= 0:
            raise ValueError("Hosted-provider budget must be finite and positive")
        remaining_budget = configured_budget
    budget_exhausted = False
    for scenario in selected:
        record = run_case(CASES[scenario], strategy, cap_usd=remaining_budget)
        with record_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        records.append(record)
        if remaining_budget is not None:
            if "agent" in record:
                remaining_budget -= record["agent"]["budget_charge_usd"]
            elif record.get("failure", {}).get("phase") == "execution":
                # A failed Job may have made a paid call without returning usage.
                # Stop further calls rather than risk exceeding the declared cap.
                remaining_budget = 0
            if remaining_budget <= 0 and scenario != selected[-1]:
                budget_exhausted = True
                break
    case_results = [
        {
            "scenario": record["scenario"],
            "passed": record["passed"],
            "invalid_setup": record["invalid_setup"],
            "decision": record.get("agent", {}).get("decision"),
            "independent_check": record.get("independent_check"),
            "score": record.get("score"),
            "failure": record.get("failure"),
        }
        for record in records
    ]
    return {
        "execution_mode": "kubernetes_development",
        "benchmark_eligible": False,
        "strategy": strategy,
        "attempts": len(records),
        "valid_attempts": sum(not r["invalid_setup"] for r in records),
        "passed_attempts": sum(r["passed"] for r in records),
        "invalid_setups": sum(r["invalid_setup"] for r in records),
        "api_cost_usd": round(sum(r.get("agent", {}).get("api_cost_usd", 0) for r in records), 8),
        "budget_charge_usd": round(
            sum(r.get("agent", {}).get("budget_charge_usd", 0) for r in records), 8
        ),
        "api_cost_complete": all(
            r.get("agent", {}).get("api_cost_complete", True) for r in records
        ),
        "configured_budget_usd": configured_budget,
        "budget_exhausted": budget_exhausted,
        "passed": len(records) == len(selected) and all(r["passed"] for r in records),
        "case_results": case_results,
        "records": str(record_path),
    }
