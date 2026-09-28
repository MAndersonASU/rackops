"""Trusted lab operator. This module MUST NOT be exposed to runtime agents.

Scenario truth and injection are confined to this trusted test-runner module.
"""

import json
import math
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

from rackops.criterion import CURRENT

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = "kind-rackops"
NAMESPACE = "rackops-lab"
STATE = ROOT / "work" / "lab-incident.json"
LABEL = {"rackops.io/lab": "rackops"}
SCENARIOS = ("bad_redis_host", "bad_service_port", "bad_image", "redis_outage", "healthy")
DEFAULT_FAULTS = {
    "bad_redis_host": "redis-invalid",
    "bad_service_port": 6553,
    "bad_image": "rackops-api:missing",
    "redis_outage": 0,
}
PROVIDER_ENV = (
    "OPENAI_API_KEY",
    "RACKOPS_LLM_MODEL",
    "RACKOPS_LLM_BUDGET_USD",
    "RACKOPS_LLM_INPUT_USD_PER_MILLION",
    "RACKOPS_LLM_OUTPUT_USD_PER_MILLION",
    "RACKOPS_LLM_MAX_ATTEMPTS",
)


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


def app_replicas_location(obj):
    value = obj["spec"]["replicas"]
    if type(value) is not int or not 1 <= value <= 2:
        raise RuntimeError("Unexpected lab API replica count")
    return "/spec/replicas", value


def replicas_location(obj):
    value = obj["spec"]["replicas"]
    if type(value) is not int or not 0 <= value <= 1:
        raise RuntimeError("Unexpected lab Redis replica count")
    return "/spec/replicas", value


def patch_field(kind, name, obj, path, before, value):
    if (kind, name) == ("deployment", "rackops-api"):
        allowed = (
            path == host_location(obj)[0]
            or path == image_location(obj)[0]
            or (path == "/spec/replicas" and path == app_replicas_location(obj)[0])
        )
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


def set_api_replicas(value: int):
    """Apply a bounded trusted-runner workload variation outside agent permissions."""
    if type(value) is not int or value not in {1, 2}:
        raise ValueError("Holdout API replicas must be 1 or 2")
    obj = deployment()
    path, before = app_replicas_location(obj)
    if before != value:
        patch_field("deployment", "rackops-api", obj, path, before, value)
        kube("rollout", "status", "deployment/rackops-api", "--timeout=120s", timeout=140)


def validate_fault(scenario: str, fault):
    if scenario == "healthy":
        if fault is not None:
            raise ValueError("Healthy holdout cases cannot specify a fault")
        return None
    if scenario not in DEFAULT_FAULTS:
        raise ValueError("Unknown incident scenario")
    value = DEFAULT_FAULTS[scenario] if fault is None else fault
    valid = (
        scenario == "bad_redis_host"
        and type(value) is str
        and (value == "redis-invalid" or re.fullmatch(r"redis-unreachable-[a-z0-9-]{1,32}", value))
        or scenario == "bad_service_port"
        and type(value) is int
        and 1 <= value <= 65535
        and value != 8000
        or scenario == "bad_image"
        and type(value) is str
        and (
            value == "rackops-api:missing"
            or re.fullmatch(r"rackops-api:holdout-missing-[a-z0-9-]{1,24}", value)
        )
        or scenario == "redis_outage"
        and value == 0
    )
    if not valid:
        raise ValueError("Fault variation is outside the trusted holdout allowlist")
    return value


def readiness():
    for name in ("redis", "rackops-api", "prometheus", "health-probe"):
        kube("rollout", "status", f"deployment/{name}", "--timeout=120s", timeout=140)


def request_check(
    duration_seconds: int | None = None,
    *,
    rate: int | None = None,
    latency_limit_ms: float | None = None,
    criterion: str | None = None,
) -> dict:
    """Run a fresh job against the Service, not a port-forward bound to an old Pod."""
    if duration_seconds is not None and duration_seconds not in range(1, 121):
        raise ValueError("Request check duration must be 1..120 seconds")
    if duration_seconds is not None:
        rate = CURRENT.requests_per_second if rate is None else rate
        latency_limit_ms = (
            CURRENT.latency_limit_ms if latency_limit_ms is None else latency_limit_ms
        )
        criterion = CURRENT.name if criterion is None else criterion
        if (
            type(latency_limit_ms) not in {int, float}
            or not math.isfinite(latency_limit_ms)
            or latency_limit_ms <= 0
            or type(rate) is not int
            or rate not in range(1, 21)
            or type(criterion) is not str
            or not re.fullmatch(r"[a-z0-9_.-]{1,64}", criterion)
        ):
            raise ValueError("Request check criterion is invalid")
    name = "rackops-check-" + uuid.uuid4().hex[:8]
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "namespace": NAMESPACE, "labels": LABEL},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 30 if duration_seconds is None else duration_seconds + 30,
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
                            "command": [
                                "python",
                                "-m",
                                "rackops.loadgen",
                                "--once" if duration_seconds is None else "--duration",
                                *([] if duration_seconds is None else [str(duration_seconds)]),
                                *(
                                    []
                                    if duration_seconds is None
                                    else [
                                        "--latency-limit-ms",
                                        str(latency_limit_ms),
                                        "--rate",
                                        str(rate),
                                        "--criterion",
                                        criterion,
                                    ]
                                ),
                            ],
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
        deadline = time.monotonic() + (40 if duration_seconds is None else duration_seconds + 40)
        while time.monotonic() < deadline:
            obj = json.loads(kube("get", "job", name, "-o", "json").stdout)
            status = obj.get("status", {})
            if status.get("succeeded") or status.get("failed"):
                logs = kube("logs", f"job/{name}", "--tail=1").stdout
                try:
                    result = json.loads(logs)
                    if type(result) is not dict or type(result.get("passed")) is not bool:
                        raise ValueError("Invalid checker output")
                    if duration_seconds is None:
                        if result.get("requests") != 4:
                            raise ValueError("Invalid smoke request count")
                    elif (
                        result.get("requested_duration_seconds") != duration_seconds
                        or result.get("requested_rate") != rate
                        or result.get("latency_limit_ms") != latency_limit_ms
                        or result.get("criterion") != criterion
                        or result.get("duration_seconds", 0) < duration_seconds
                        or type(result.get("requests")) is not int
                        or not 0 <= result["requests"] <= duration_seconds * rate
                        or type(result.get("successes")) is not int
                        or not 0 <= result["successes"] <= result["requests"]
                    ):
                        raise ValueError("Invalid full-window checker output")
                    return result
                except (ValueError, TypeError) as exc:
                    raise RuntimeError(
                        "Invalid setup: checker did not produce a valid request result"
                    ) from exc
            time.sleep(1)
        raise RuntimeError("Invalid setup: request-check Job did not finish")
    finally:
        kube("delete", "job", name, "--ignore-not-found", "--wait=false", check=False)


def metrics_check() -> dict:
    """Verify the labeled in-cluster load is visible in Prometheus."""
    name = "rackops-metrics-" + uuid.uuid4().hex[:8]
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "namespace": NAMESPACE, "labels": LABEL},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 45,
            "ttlSecondsAfterFinished": 120,
            "template": {
                "metadata": {"labels": LABEL},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "containers": [
                        {
                            "name": "metrics-check",
                            "image": "rackops-api:dev",
                            "imagePullPolicy": "Never",
                            "command": ["python", "-m", "rackops.metrics_check"],
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
        deadline = time.monotonic() + 55
        while time.monotonic() < deadline:
            obj = json.loads(kube("get", "job", name, "-o", "json").stdout)
            status = obj.get("status", {})
            if status.get("succeeded") or status.get("failed"):
                logs = kube("logs", f"job/{name}", "--tail=1").stdout
                try:
                    result = json.loads(logs)
                except ValueError as exc:
                    raise RuntimeError("Metrics check returned invalid output") from exc
                if (
                    type(result) is not dict
                    or type(result.get("passed")) is not bool
                    or result.get("metric") != "rackops_http_requests_total_rate"
                ):
                    raise RuntimeError("Metrics check returned an unexpected result")
                return result
            time.sleep(1)
        raise RuntimeError("Metrics check Job did not finish")
    finally:
        kube("delete", "job", name, "--ignore-not-found", "--wait=false", check=False)


def run_baseline_job() -> dict:
    """Trusted runner creates a restricted Pod; its code gets no runner credentials."""
    guard()
    name = "rackops-baseline-" + uuid.uuid4().hex[:8]
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "namespace": NAMESPACE, "labels": LABEL},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 260,
            "ttlSecondsAfterFinished": 120,
            "template": {
                "metadata": {"labels": LABEL},
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": "rackops-agent",
                    "automountServiceAccountToken": True,
                    "securityContext": {"runAsNonRoot": True, "runAsUser": 10001},
                    "containers": [
                        {
                            "name": "baseline",
                            "image": "rackops-api:dev",
                            "imagePullPolicy": "Never",
                            "command": ["python", "-m", "rackops.baseline_job"],
                            "resources": {
                                "requests": {"cpu": "50m", "memory": "96Mi"},
                                "limits": {"cpu": "500m", "memory": "192Mi"},
                            },
                        }
                    ],
                },
            },
        },
    }
    kube("create", "-f", "-", input_data=json.dumps(job))
    try:
        deadline = time.monotonic() + 270
        while time.monotonic() < deadline:
            obj = json.loads(kube("get", "job", name, "-o", "json").stdout)
            status = obj.get("status", {})
            if status.get("succeeded") or status.get("failed"):
                logs = kube("logs", f"job/{name}").stdout
                raw = ROOT / "results" / "raw"
                raw.mkdir(parents=True, exist_ok=True)
                (raw / f"{name}.log").write_text(logs, encoding="utf-8")
                try:
                    result = json.loads(logs.splitlines()[-1])
                except (ValueError, IndexError) as exc:
                    raise RuntimeError("Baseline Job did not return a valid result") from exc
                if (
                    type(result) is not dict
                    or type(result.get("decision")) is not dict
                    or type(result.get("repair_attempts")) is not int
                    or type(result.get("tool_calls")) is not int
                    or result.get("execution_mode") != "kubernetes"
                    or result.get("strategy") != "runbook"
                ):
                    raise RuntimeError("Baseline Job returned an unexpected result")
                return result
            time.sleep(2)
        raise RuntimeError("Baseline Job exceeded its 270-second runner limit")
    finally:
        kube("delete", "job", name, "--ignore-not-found", "--wait=false", check=False)


def run_agent_job(strategy: str, *, cap_usd: float | None = None) -> dict:
    """Run one hosted strategy with an ephemeral provider Secret and restricted identity."""
    if strategy not in {"basic", "structured"}:
        raise ValueError("Hosted strategy must be basic or structured")
    guard()
    settings = {name: os.getenv(name, "").strip() for name in PROVIDER_ENV}
    settings["RACKOPS_LLM_MAX_ATTEMPTS"] = settings["RACKOPS_LLM_MAX_ATTEMPTS"] or "2"
    missing = [name for name, value in settings.items() if not value]
    if missing:
        raise ValueError("Hosted-provider environment is incomplete")
    if cap_usd is not None:
        if type(cap_usd) is not float or cap_usd <= 0:
            raise ValueError("Remaining hosted-provider budget must be positive")
        configured = float(settings["RACKOPS_LLM_BUDGET_USD"])
        settings["RACKOPS_LLM_BUDGET_USD"] = str(min(configured, cap_usd))

    suffix = uuid.uuid4().hex[:8]
    name = f"rackops-{strategy}-{suffix}"
    secret_name = f"rackops-provider-{suffix}"
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": secret_name, "namespace": NAMESPACE, "labels": LABEL},
        "type": "Opaque",
        "stringData": settings,
    }
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "namespace": NAMESPACE, "labels": LABEL},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 300,
            "ttlSecondsAfterFinished": 120,
            "template": {
                "metadata": {"labels": LABEL},
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": "rackops-agent",
                    "automountServiceAccountToken": True,
                    "securityContext": {"runAsNonRoot": True, "runAsUser": 10001},
                    "containers": [
                        {
                            "name": "agent",
                            "image": "rackops-api:dev",
                            "imagePullPolicy": "Never",
                            "command": ["python", "-m", "rackops.agent_job"],
                            "env": [{"name": "RACKOPS_STRATEGY", "value": strategy}],
                            "envFrom": [{"secretRef": {"name": secret_name}}],
                            "resources": {
                                "requests": {"cpu": "50m", "memory": "96Mi"},
                                "limits": {"cpu": "500m", "memory": "192Mi"},
                            },
                        }
                    ],
                },
            },
        },
    }
    secret_created = False
    try:
        kube("create", "-f", "-", input_data=json.dumps(secret))
        secret_created = True
        kube("create", "-f", "-", input_data=json.dumps(job))
        deadline = time.monotonic() + 310
        while time.monotonic() < deadline:
            obj = json.loads(kube("get", "job", name, "-o", "json").stdout)
            status = obj.get("status", {})
            if status.get("succeeded") or status.get("failed"):
                logs = kube("logs", f"job/{name}").stdout
                raw = ROOT / "results" / "raw"
                raw.mkdir(parents=True, exist_ok=True)
                (raw / f"{name}.log").write_text(logs, encoding="utf-8")
                try:
                    result = json.loads(logs.splitlines()[-1])
                except (ValueError, IndexError) as exc:
                    raise RuntimeError("Hosted agent Job did not return a valid result") from exc
                if (
                    type(result) is not dict
                    or result.get("execution_mode") != "kubernetes_hosted_provider"
                    or result.get("strategy") != strategy
                    or type(result.get("decision")) is not dict
                    or type(result.get("repair_attempts")) is not int
                    or type(result.get("tool_calls")) is not int
                    or type(result.get("input_tokens")) is not int
                    or type(result.get("output_tokens")) is not int
                    or type(result.get("api_cost_usd")) not in {int, float}
                    or type(result.get("budget_charge_usd")) not in {int, float}
                    or type(result.get("api_cost_complete")) is not bool
                ):
                    raise RuntimeError("Hosted agent Job returned an unexpected result")
                return result
            time.sleep(2)
        raise RuntimeError("Hosted agent Job exceeded its 310-second runner limit")
    finally:
        kube("delete", "job", name, "--ignore-not-found", "--wait=false", check=False)
        if secret_created:
            kube(
                "delete",
                "secret",
                secret_name,
                "--ignore-not-found",
                "--wait=false",
                check=False,
            )


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
    if scenario == "redis_outage":
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            obj = named_resource("deployment", "redis")
            if (
                obj["spec"]["replicas"] == 0
                and obj.get("status", {}).get("observedGeneration", 0)
                >= obj["metadata"].get("generation", 0)
                and obj.get("status", {}).get("readyReplicas", 0) == 0
            ):
                return
            time.sleep(1)
        raise RuntimeError("Invalid setup: Redis still has ready replicas")
    if scenario in {"bad_redis_host", "bad_image"}:
        kube(
            "wait",
            "deployment/rackops-api",
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


def inject(scenario="bad_redis_host", *, fault=None, api_replicas=1):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown incident scenario")
    guard()
    if STATE.exists():
        raise RuntimeError("An incident snapshot already exists; recover or reset it first")
    if api_replicas != 1:
        set_api_replicas(api_replicas)
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
    fault = validate_fault(scenario, fault)
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


def run(
    action, scenario="bad_redis_host", expected=None, expected_cause=None, expected_repairs=None
):
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
    if action == "baseline":
        result = run_baseline_job()
        if expected is not None or expected_cause is not None or expected_repairs is not None:
            decision = result.get("decision", {})
            result["passed"] = (
                (expected is None or decision.get("status") == expected)
                and (expected_cause is None or decision.get("root_cause") == expected_cause)
                and (expected_repairs is None or result.get("repair_attempts") == expected_repairs)
            )
        return result
    if action == "metrics":
        guard()
        return metrics_check()
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
