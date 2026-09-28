"""In-cluster hosted-agent entry point; no scenario truth or runner token is mounted."""

import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from rackops.checker import probe
from rackops.gateway import Gateway
from rackops.kube_backend import KubeBackend
from rackops.openai_provider import OpenAIProvider
from rackops.strategies import basic, structured

STRATEGIES = {"basic": basic, "structured": structured}


def main():
    strategy = os.getenv("RACKOPS_STRATEGY", "")
    if strategy not in STRATEGIES:
        raise ValueError("RACKOPS_STRATEGY must be basic or structured")
    started = time.monotonic()
    backend = KubeBackend.from_incluster()
    try:
        provider = OpenAIProvider.from_env()
        try:

            def independent_check():
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
                        return probe(backend.application_client, duration=60, rate=5)
                    time.sleep(2)
                return {"passed": False, "reason": "rollout_not_ready_within_90_seconds"}

            record_path = Path("/tmp/rackops-run.jsonl")
            gateway = Gateway(backend, independent_check, record_path=record_path)
            observed = backend.observe_for_runbook(gateway)
            decision = STRATEGIES[strategy](gateway, observed, provider)
            result = {
                "execution_mode": "kubernetes_hosted_provider",
                "strategy": strategy,
                "benchmark_eligible": False,
                "model_id": provider.model_id,
                "decision": asdict(decision),
                "tool_calls": gateway.calls,
                "repair_attempts": gateway.repairs,
                "input_tokens": provider.last_usage["input_tokens"],
                "output_tokens": provider.last_usage["output_tokens"],
                "api_cost_usd": provider.last_usage["api_cost_usd"],
                "budget_charge_usd": provider.last_usage["budget_charge_usd"],
                "api_cost_complete": provider.last_usage["api_cost_complete"],
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
            if record_path.exists():
                for line in record_path.read_text(encoding="utf-8").splitlines():
                    print("RACKOPS_RECORD " + line, flush=True)
            print(json.dumps(result, sort_keys=True), flush=True)
        finally:
            provider.close()
    finally:
        backend.close()


if __name__ == "__main__":
    main()
