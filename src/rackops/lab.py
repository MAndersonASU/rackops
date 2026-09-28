"""Trusted lab operator. This module MUST NOT be exposed to runtime agents.

Scenario truth and injection are confined to this trusted test-runner module.
"""

import json
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = "kind-rackops"
NAMESPACE = "rackops-lab"
STATE = ROOT / "work" / "lab-incident.json"
LABEL = {"rackops.io/lab": "rackops"}
SCENARIOS = ("bad_redis_host", "bad_service_port", "bad_image", "redis_outage", "healthy")


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


def named_resource(kind, name):
    if (kind, name) not in {("service", "rackops-api"), ("deployment", "redis")}:
        raise ValueError("Resource is outside the trusted lab operator allowlist")
    obj = json.loads(kube("get", kind, name, "-o", "json").stdout)
    metadata = obj["metadata"]
    if (
        metadata.get("namespace") != NAMESPACE
        or metadata.get("labels", {}).get("rackops.io/lab") != "rackops"
    ):
        raise RuntimeError("Lab resource identity check failed")
    return obj


def service_port_location(obj):
    ports = obj["spec"]["ports"]
    if len(ports) != 1 or ports[0]["port"] != 8000:
        raise RuntimeError("Unexpected API Service port structure")
    value = ports[0]["targetPort"]
    if type(value) is not int or not 1 <= value <= 65535:
        raise RuntimeError("Expected a numeric Service target port")
    return "/spec/ports/0/targetPort", value


def image_location(obj):
    containers = obj["spec"]["template"]["spec"]["containers"]
    if len(containers) != 1 or containers[0]["name"] != "api":
        raise RuntimeError("Unexpected application image structure")
    return "/spec/template/spec/containers/0/image", containers[0]["image"]


def replicas_location(obj):
    value = obj["spec"]["replicas"]
    if type(value) is not int or not 0 <= value <= 1:
        raise RuntimeError("Unexpected lab Redis replica count")
    return "/spec/replicas", value


def patch_field(kind, name, obj, path, before, value):
    if (kind, name) == ("deployment", "rackops-api"):
        allowed = path == host_location(obj)[0] or path == image_location(obj)[0]
    elif (kind, name) == ("service", "rackops-api"):
        allowed = path == service_port_location(obj)[0]
    elif (kind, name) == ("deployment", "redis"):
        allowed = path == replicas_location(obj)[0]
    else:
        allowed = False
    if not allowed:
        raise ValueError("Field is outside the trusted lab operator allowlist")
    if before == value or type(before) is not type(value):
        raise ValueError("Invalid field change")
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
    kube("patch", kind, name, "--type=json", "-p", json.dumps(patch))


def host_location(obj):
    env = obj["spec"]["template"]["spec"]["containers"][0]["env"]
    matches = [(i, e) for i, e in enumerate(env) if e["name"] == "RACKOPS_REDIS_HOST"]
    if len(matches) != 1 or "value" not in matches[0][1]:
        raise RuntimeError("Expected exactly one plain Redis host setting")
    index, item = matches[0]
    return f"/spec/template/spec/containers/0/env/{index}/value", item["value"]


def patch_host(obj, value):
    path, before = host_location(obj)
    patch_field("deployment", "rackops-api", obj, path, before, value)


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


def scenario_resource(scenario):
    if scenario in {"bad_redis_host", "bad_image"}:
        obj = deployment()
        location = host_location if scenario == "bad_redis_host" else image_location
        return "deployment", "rackops-api", obj, location
    if scenario == "bad_service_port":
        obj = named_resource("service", "rackops-api")
        return "service", "rackops-api", obj, service_port_location
    if scenario == "redis_outage":
        obj = named_resource("deployment", "redis")
        return "deployment", "redis", obj, replicas_location
    raise ValueError("Unknown incident scenario")


def wait_for_fault(scenario):
    if scenario in {"bad_redis_host", "bad_image", "redis_outage"}:
        name = "redis" if scenario == "redis_outage" else "rackops-api"
        kube(
            "wait",
            f"deployment/{name}",
            "--for=condition=Available=false",
            "--timeout=60s",
            timeout=75,
        )
    if scenario == "bad_image":
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            pods = json.loads(kube("get", "pods", "-l", "app=rackops-api", "-o", "json").stdout)
            reasons = {
                status.get("state", {}).get("waiting", {}).get("reason")
                for pod in pods.get("items", [])
                for status in pod.get("status", {}).get("containerStatuses", [])
            }
            if reasons & {"ErrImageNeverPull", "ImagePullBackOff", "ErrImagePull"}:
                return
            time.sleep(1)
        raise RuntimeError("Invalid setup: unavailable image has no image failure status")


def inject(scenario="bad_redis_host"):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown incident scenario")
    guard()
    if STATE.exists():
        raise RuntimeError("An incident snapshot already exists; recover or reset it first")
    baseline = request_check()
    if not baseline["passed"]:
        raise RuntimeError("Invalid setup: baseline requests are not healthy")
    if scenario == "healthy":
        return {
            "execution_mode": "kubernetes",
            "scenario": scenario,
            "passed": True,
            "requests": baseline,
            "mutation_count": 0,
            "benchmark_eligible": False,
        }
    kind, name, obj, location = scenario_resource(scenario)
    path, before = location(obj)
    fault = {
        "bad_redis_host": "redis-invalid",
        "bad_service_port": 6553,
        "bad_image": "rackops-api:missing",
        "redis_outage": 0,
    }[scenario]
    if before == fault:
        raise RuntimeError("Invalid setup: baseline already matches the fault")
    snapshot = {
        "scenario": scenario,
        "kind": kind,
        "name": name,
        "uid": obj["metadata"]["uid"],
        "before": before,
        "fault": fault,
        "status": "prepared",
    }
    STATE.parent.mkdir(exist_ok=True)
    # Exclusive create prevents two injectors from overwriting the recovery snapshot.
    with STATE.open("x", encoding="utf-8") as stream:
        json.dump(snapshot, stream, indent=2)
    patch_field(kind, name, obj, path, before, fault)
    wait_for_fault(scenario)
    failed = request_check()
    # A bad image can leave old replicas serving on other rollout strategies.
    if scenario != "bad_image" and failed["successes"] != 0:
        raise RuntimeError("Invalid setup: fault did not manifest; use lab recover")
    snapshot["status"] = "fault_confirmed"
    STATE.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return {
        "execution_mode": "kubernetes",
        "scenario": scenario,
        "fault_confirmed": True,
        "requests": failed,
        "user_facing_outage_observed": failed["successes"] == 0,
        "rollout_failure_observed": scenario == "bad_image",
        "next_action": "rackops lab recover",
        "benchmark_eligible": False,
    }


def recover():
    guard()
    if not STATE.exists():
        raise RuntimeError("No local incident snapshot exists")
    snapshot = json.loads(STATE.read_text(encoding="utf-8"))
    scenario = snapshot.get("scenario")
    kind, name, obj, location = scenario_resource(scenario)
    if (snapshot.get("kind"), snapshot.get("name")) != (kind, name):
        raise RuntimeError("Incident snapshot resource identity invalid")
    if obj["metadata"]["uid"] != snapshot["uid"]:
        raise RuntimeError("Resource identity changed; refusing recovery")
    path, current = location(obj)
    if current == snapshot["fault"]:
        patch_field(kind, name, obj, path, current, snapshot["before"])
    elif current != snapshot["before"]:
        raise RuntimeError("Concurrent field change detected; refusing to overwrite it")
    readiness()
    result = request_check()
    if not result["passed"]:
        raise RuntimeError("Recovery failed independent request checks; snapshot retained")
    STATE.unlink()
    return {
        "execution_mode": "kubernetes",
        "scenario": scenario,
        "passed": True,
        "requests": result,
        "benchmark_eligible": False,
        "repair": "restore recorded pre-injection field",
    }


def run(action, scenario="bad_redis_host"):
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
        return inject(scenario)
    if action == "recover":
        return recover()
    guard()
    if action == "reset":
        # Reset is a trusted runner operation, not an agent rollback.
        if STATE.exists():
            recover()
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
