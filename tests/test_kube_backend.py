import json
from pathlib import Path

import httpx
import pytest
import yaml

from rackops.gateway import FieldState, Gateway, PolicyDenied
from rackops.kube_backend import KubeBackend
from rackops.runbook import run


def service_object(version="7", port=6553):
    return {
        "metadata": {
            "namespace": "rackops-lab",
            "name": "rackops-api",
            "uid": "svc-uid",
            "resourceVersion": version,
            "labels": {"rackops.io/lab": "rackops"},
        },
        "spec": {"ports": [{"port": 8000, "targetPort": port}]},
    }


def test_rest_patch_checks_uid_version_and_field():
    current = service_object()
    seen_patch = []

    def handler(request):
        nonlocal current
        if request.method == "GET":
            return httpx.Response(200, json=current)
        assert request.method == "PATCH"
        assert request.url.path.endswith("/services/rackops-api")
        assert request.headers["content-type"] == "application/json-patch+json"
        patch = json.loads(request.content)
        seen_patch.extend(patch)
        assert patch[:3] == [
            {"op": "test", "path": "/metadata/uid", "value": "svc-uid"},
            {"op": "test", "path": "/metadata/resourceVersion", "value": "7"},
            {"op": "test", "path": "/spec/ports/0/targetPort", "value": 6553},
        ]
        current = service_object("8", 8000)
        return httpx.Response(200, json=current)

    with httpx.Client(
        base_url="https://kube.test", transport=httpx.MockTransport(handler)
    ) as client:
        backend = KubeBackend(client)
        before = backend.read_field("service", "rackops-api", "target_port")
        after = backend.change_field(before, 8000)
    assert after.value == 8000 and after.resource_version == "8"
    assert seen_patch[-1]["op"] == "replace"


def test_denied_targets_and_stale_versions_never_patch():
    patched = []

    def handler(request):
        if request.method == "PATCH":
            patched.append(request)
        return httpx.Response(200, json=service_object())

    with httpx.Client(
        base_url="https://kube.test", transport=httpx.MockTransport(handler)
    ) as client:
        backend = KubeBackend(client)
        with pytest.raises(PolicyDenied):
            backend.read_field("secret", "credentials", "data")
        with pytest.raises(PolicyDenied):
            backend.change_field(FieldState("deployment", "redis", "replicas", 0, "uid", "1"), 1)
        stale = FieldState("service", "rackops-api", "target_port", 6553, "svc-uid", "6")
        with pytest.raises(PolicyDenied, match="stale"):
            backend.change_field(stale, 8000)
    assert patched == []


def test_server_error_cannot_leak_response_or_token():
    secret = "private-fixture-token"

    def handler(request):
        return httpx.Response(403, text=f"denied: {secret}")

    with httpx.Client(
        base_url="https://kube.test",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": f"Bearer {secret}"},
    ) as client:
        with pytest.raises(RuntimeError) as captured:
            KubeBackend(client).read_field("service", "rackops-api", "target_port")
    assert secret not in str(captured.value)


def test_lab_marker_rejected_when_wrong_cluster():
    def handler(request):
        return httpx.Response(
            200, json={"metadata": {"namespace": "rackops-lab"}, "data": {"cluster": "other"}}
        )

    with httpx.Client(
        base_url="https://kube.test", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(PolicyDenied, match="marker"):
            KubeBackend(client).verify_lab_marker()


def test_namespaced_role_excludes_secret_and_redis_patch():
    manifest = Path(__file__).resolve().parents[1] / "lab" / "manifests.yaml"
    objects = list(yaml.safe_load_all(manifest.read_text(encoding="utf-8")))
    roles = [o for o in objects if o["kind"] == "Role"]
    assert len(roles) == 1
    role = roles[0]
    assert role["metadata"]["namespace"] == "rackops-lab"
    assert all("secrets" not in rule["resources"] for rule in role["rules"])
    assert all(
        not set(rule["verbs"]) & {"create", "delete", "update", "*"} for rule in role["rules"]
    )
    for rule in role["rules"]:
        if "deployments" in rule["resources"] and "patch" in rule["verbs"]:
            assert rule["resourceNames"] == ["rackops-api"]
        if "services" in rule["resources"] and "patch" in rule["verbs"]:
            assert rule["resourceNames"] == ["rackops-api"]


def test_observed_history_drives_runbook_through_restricted_adapter():
    app = {
        "metadata": {
            "namespace": "rackops-lab",
            "name": "rackops-api",
            "uid": "api-uid",
            "resourceVersion": "10",
            "generation": 2,
            "labels": {"rackops.io/lab": "rackops"},
        },
        "spec": {
            "replicas": 1,
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "api",
                            "image": "rackops-api:missing",
                            "env": [{"name": "RACKOPS_REDIS_HOST", "value": "redis"}],
                            "ports": [{"containerPort": 8000}],
                        }
                    ]
                }
            },
        },
        "status": {"observedGeneration": 2, "updatedReplicas": 0, "availableReplicas": 0},
    }
    redis = {
        "metadata": {
            "namespace": "rackops-lab",
            "name": "redis",
            "uid": "redis-uid",
            "resourceVersion": "4",
            "labels": {"rackops.io/lab": "rackops"},
        },
        "spec": {"replicas": 1},
    }
    history = {
        "items": [
            {
                "metadata": {
                    "namespace": "rackops-lab",
                    "ownerReferences": [{"uid": "api-uid"}],
                    "annotations": {"deployment.kubernetes.io/revision": "1"},
                },
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": "api",
                                    "image": "rackops-api:dev",
                                    "env": [{"name": "RACKOPS_REDIS_HOST", "value": "redis"}],
                                }
                            ]
                        }
                    }
                },
            }
        ]
    }

    def kubernetes(request):
        if request.url.path.endswith("/deployments/rackops-api"):
            if request.method == "PATCH":
                patch = json.loads(request.content)
                assert patch[-1] == {
                    "op": "replace",
                    "path": "/spec/template/spec/containers/0/image",
                    "value": "rackops-api:dev",
                }
                app["spec"]["template"]["spec"]["containers"][0]["image"] = "rackops-api:dev"
                app["metadata"]["resourceVersion"] = "11"
            return httpx.Response(200, json=app)
        if request.url.path.endswith("/deployments/redis"):
            return httpx.Response(200, json=redis)
        if request.url.path.endswith("/services/rackops-api"):
            return httpx.Response(200, json=service_object("3", 8000))
        if request.url.path.endswith("/replicasets"):
            return httpx.Response(200, json=history)
        if request.url.path.endswith("/events") or request.url.path.endswith("/pods"):
            return httpx.Response(200, json={"items": []})
        raise AssertionError(f"Unexpected API path: {request.url.path}")

    values = {}

    def application(request):
        key = request.url.path.split("/")[-1]
        if request.method == "PUT":
            values[key] = json.loads(request.read())["value"]
        if key not in values:
            return httpx.Response(404)
        return httpx.Response(200, json={"key": key, "value": values[key]})

    def prometheus(_request):
        return httpx.Response(200, json={"data": {"result": [{"value": [0, "5"]}]}})

    with (
        httpx.Client(base_url="https://kube.test", transport=httpx.MockTransport(kubernetes)) as kc,
        httpx.Client(
            base_url="http://rackops-api:8000", transport=httpx.MockTransport(application)
        ) as ac,
        httpx.Client(
            base_url="http://prometheus:9090", transport=httpx.MockTransport(prometheus)
        ) as mc,
    ):
        backend = KubeBackend(kc, application_client=ac, metrics_client=mc)
        gateway = Gateway(backend, lambda: {"passed": True})
        observed = backend.observe_for_runbook(gateway)
        assert observed.probe_passed
        assert not observed.rollout_ready
        assert observed.prior_images == ("rackops-api:dev",)
        decision = run(gateway, observed)
    assert decision.root_cause == "broken_image"
    assert decision.status == "verified_repair"
    assert app["spec"]["template"]["spec"]["containers"][0]["image"] == "rackops-api:dev"
