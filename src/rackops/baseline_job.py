"""In-cluster deterministic runbook entry point. No scenario truth is mounted."""

import json
import time
from dataclasses import asdict
from pathlib import Path

from rackops.checker import probe
from rackops.criterion import CURRENT
from rackops.gateway import Gateway
from rackops.kube_backend import KubeBackend
from rackops.runbook import run


def main():
    started = time.monotonic()
    backend = KubeBackend.from_incluster()
    try:

        def independent_check():
            # Deployment rollouts can take time after a valid patch. Only the
            # subsequent full request window counts toward recovery.
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                obj = backend._resource("deployment", "rackops-api")
                desired = obj["spec"].get("replicas", 1)
                status = obj.get("status", {})
                if (
                    status.get("observedGeneration", 0) >= obj["metadata"].get("generation", 0)
                    and status.get("updatedReplicas", 0) == desired
                    and status.get("availableReplicas", 0) == desired
                ):
                    return probe(
                        backend.application_client,
                        duration=CURRENT.duration_seconds,
                        rate=CURRENT.requests_per_second,
                        latency_limit_ms=CURRENT.latency_limit_ms,
                        criterion=CURRENT.name,
                    )
                time.sleep(2)
            return {"passed": False, "reason": "rollout_not_ready_within_90_seconds"}

        gateway = Gateway(backend, independent_check, record_path=Path("/tmp/rackops-run.jsonl"))
        observed = backend.observe_for_runbook(gateway)
        decision = run(gateway, observed)
        result = {
            "execution_mode": "kubernetes",
            "strategy": "runbook",
            "benchmark_eligible": False,
            "decision": asdict(decision),
            "tool_calls": gateway.calls,
            "repair_attempts": gateway.repairs,
            "attempted_policy_violations": gateway.policy_denials,
            "actions": [
                {
                    "id": action.id,
                    "kind": action.kind,
                    "name": action.name,
                    "field": action.field,
                    "status": action.status,
                    "rollback_status": action.rollback_status,
                }
                for action in gateway.actions.values()
            ],
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        records = Path("/tmp/rackops-run.jsonl")
        if records.exists():
            for line in records.read_text(encoding="utf-8").splitlines():
                print("RACKOPS_RECORD " + line, flush=True)
        print(json.dumps(result, sort_keys=True), flush=True)
    finally:
        backend.close()


if __name__ == "__main__":
    main()
