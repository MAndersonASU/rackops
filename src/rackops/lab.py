"""Trusted lab operator. This module MUST NOT be exposed to runtime agents.

Only the first fault (bad Redis host) is implemented in this milestone.
"""

import json
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = "kind-rackops"
NAMESPACE = "rackops-lab"
STATE = ROOT / "work" / "dependency-incident.json"
LABEL = {"rackops.io/lab": "rackops"}


def command(args: list[str], *, timeout=180, input_data=None, check=True):
    try:
        result = subprocess.run(
            args, input=input_data, text=True, capture_output=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            f"{args[0]} unavailable or timed out; inspect your local installation"
        ) from exc
    if check and result.returncode:
        # Avoid emitting unsanitized kubeconfig paths or credentials from subprocess errors.
        raise RuntimeError(
            f"{args[0]} command failed (exit {result.returncode}); inspect the lab locally"
        )
    return result


def kube(*args, **kwargs):
    return command(
        ["kubectl", "--context", CONTEXT, "--namespace", NAMESPACE, "--request-timeout=15s", *args],
        **kwargs,
    )


def guard():
    clusters = command(["kind", "get", "clusters"], timeout=20).stdout.splitlines()
    if "rackops" not in clusters:
        raise RuntimeError("The named kind cluster rackops does not exist")
    namespace = json.loads(kube("get", "namespace", NAMESPACE, "-o", "json").stdout)
    if namespace["metadata"].get("labels", {}).get("rackops.io/lab") != "rackops":
        raise RuntimeError("Lab namespace identity check failed; refusing mutation")


def deployment():
    obj = json.loads(kube("get", "deployment", "rackops-api", "-o", "json").stdout)
    if obj["metadata"].get("labels", {}).get("rackops.io/lab") != "rackops":
        raise RuntimeError("Application identity check failed")
    containers = obj["spec"]["template"]["spec"]["containers"]
    if len(containers) != 1 or containers[0]["name"] != "api":
        raise RuntimeError("Unexpected deployment container structure")
    return obj


def host_location(obj):
    env = obj["spec"]["template"]["spec"]["containers"][0]["env"]
    matches = [(i, e) for i, e in enumerate(env) if e["name"] == "RACKOPS_REDIS_HOST"]
    if len(matches) != 1 or "value" not in matches[0][1]:
        raise RuntimeError("Expected exactly one plain Redis host setting")
    index, item = matches[0]
    return f"/spec/template/spec/containers/0/env/{index}/value", item["value"]


def patch_host(obj, value):
    path, before = host_location(obj)
    patch = [
        {"op": "test", "path": "/metadata/uid", "value": obj["metadata"]["uid"]},
        {
            "op": "test",
            "path": "/metadata/resourceVersion",
            "value": obj["metadata"]["resourceVersion"],
        },
        {"op": "test", "path": path, "value": before},
        {"op": "replace", "path": path, "value": value},
    ]
    kube("patch", "deployment", "rackops-api", "--type=json", "-p", json.dumps(patch))


def readiness():
    for name in ("redis", "rackops-api", "prometheus", "health-probe"):
        kube("rollout", "status", f"deployment/{name}", "--timeout=120s", timeout=140)


def request_check() -> dict:
    """Run a fresh job against the Service, not a port-forward bound to an old Pod."""
    name = "rackops-check-" + uuid.uuid4().hex[:8]
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "namespace": NAMESPACE, "labels": LABEL},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 30,
            "ttlSecondsAfterFinished": 120,
            "template": {
                "metadata": {"labels": LABEL},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "containers": [
                        {
                            "name": "check",
                            "image": "rackops-api:dev",
                            "imagePullPolicy": "Never",
                            "command": ["python", "-m", "rackops.loadgen", "--once"],
                            "resources": {
                                "requests": {"cpu": "25m", "memory": "64Mi"},
                                "limits": {"cpu": "250m", "memory": "128Mi"},
                            },
                        }
                    ],
                },
            },
        },
    }
    kube("create", "-f", "-", input_data=json.dumps(job))
    try:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            obj = json.loads(kube("get", "job", name, "-o", "json").stdout)
            status = obj.get("status", {})
            if status.get("succeeded") or status.get("failed"):
                logs = kube("logs", f"job/{name}", "--tail=1").stdout
                try:
                    result = json.loads(logs)
                    if result.get("requests") != 4 or type(result.get("passed")) is not bool:
                        raise ValueError("Invalid checker output")
                    return result
                except (ValueError, TypeError) as exc:
                    raise RuntimeError(
                        "Invalid setup: checker did not produce a valid request result"
                    ) from exc
            time.sleep(1)
        raise RuntimeError("Invalid setup: request-check Job did not finish")
    finally:
        kube("delete", "job", name, "--ignore-not-found", "--wait=false", check=False)


def inject():
    guard()
    if STATE.exists():
        raise RuntimeError("An incident snapshot already exists; recover or reset it first")
    if not request_check()["passed"]:
        raise RuntimeError("Invalid setup: baseline requests are not healthy")
    obj = deployment()
    _, before = host_location(obj)
    snapshot = {
        "uid": obj["metadata"]["uid"],
        "before_host": before,
        "fault_host": "redis-invalid",
        "status": "prepared",
    }
    STATE.parent.mkdir(exist_ok=True)
    # Exclusive create prevents two injectors from overwriting the recovery snapshot.
    with STATE.open("x", encoding="utf-8") as stream:
        json.dump(snapshot, stream, indent=2)
    patch_host(obj, snapshot["fault_host"])
    kube(
        "wait",
        "deployment/rackops-api",
        "--for=condition=Available=false",
        "--timeout=60s",
        timeout=75,
    )
    failed = request_check()
    if failed["successes"] != 0:
        raise RuntimeError("Invalid setup: fault did not manifest; use lab recover")
    snapshot["status"] = "fault_confirmed"
    STATE.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return {
        "execution_mode": "kubernetes",
        "fault_confirmed": True,
        "requests": failed,
        "next_action": "rackops lab recover",
        "benchmark_eligible": False,
    }


def recover():
    guard()
    if not STATE.exists():
        raise RuntimeError("No local incident snapshot exists")
    snapshot = json.loads(STATE.read_text(encoding="utf-8"))
    obj = deployment()
    if obj["metadata"]["uid"] != snapshot["uid"]:
        raise RuntimeError("Deployment identity changed; refusing recovery")
    _, current = host_location(obj)
    if current == snapshot["fault_host"]:
        patch_host(obj, snapshot["before_host"])
    elif current != snapshot["before_host"]:
        raise RuntimeError("Concurrent host change detected; refusing to overwrite it")
    readiness()
    result = request_check()
    if not result["passed"]:
        raise RuntimeError("Recovery failed independent request checks; snapshot retained")
    STATE.unlink()
    return {
        "execution_mode": "kubernetes",
        "passed": True,
        "requests": result,
        "benchmark_eligible": False,
        "repair": "restore pre-injection Redis host",
    }


def run(action):
    if action == "up":
        if (
            command(["docker", "info", "--format", "{{.OSType}}"], timeout=20).stdout.strip()
            != "linux"
        ):
            raise RuntimeError("Docker must be running Linux containers")
        clusters = command(["kind", "get", "clusters"]).stdout.splitlines()
        if "rackops" in clusters:
            raise RuntimeError("Cluster rackops already exists; use lab reset after inspecting it")
        command(
            [
                "docker",
                "build",
                "-t",
                "rackops-api:dev",
                "-f",
                str(ROOT / "lab/Dockerfile"),
                str(ROOT),
            ],
            timeout=600,
        )
        command(
            [
                "kind",
                "create",
                "cluster",
                "--name",
                "rackops",
                "--config",
                str(ROOT / "lab/kind.yaml"),
                "--wait",
                "120s",
            ],
            timeout=300,
        )
        command(
            ["kind", "load", "docker-image", "rackops-api:dev", "--name", "rackops"], timeout=180
        )
        kube("apply", "-f", str(ROOT / "lab/manifests.yaml"))
        guard()
        readiness()
        return {"execution_mode": "kubernetes", **request_check()}
    if action == "inject":
        return inject()
    if action == "recover":
        return recover()
    guard()
    if action == "reset":
        # Reset is a trusted runner operation, not an agent rollback.
        kube("apply", "-f", str(ROOT / "lab/manifests.yaml"))
        readiness()
        result = request_check()
        if result["passed"]:
            STATE.unlink(missing_ok=True)
        return {"execution_mode": "kubernetes", **result}
    if action == "down":
        command(["kind", "delete", "cluster", "--name", "rackops"])
        STATE.unlink(missing_ok=True)
        return {"removed": "rackops lab cluster"}
    raise ValueError("Unknown lab action")
