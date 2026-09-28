import json
from types import SimpleNamespace

import pytest

from rackops import lab
from rackops.cli import local_url


def test_patch_tests_resource_identity_version_and_only_changes_host(monkeypatch):
    obj = {
        "metadata": {"uid": "uid-a", "resourceVersion": "3"},
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "env": [
                                {"name": "RACKOPS_REDIS_HOST", "value": "redis-invalid"},
                                {"name": "UNRELATED", "value": "preserve"},
                            ]
                        }
                    ]
                }
            }
        },
    }
    calls = []
    monkeypatch.setattr(lab, "kube", lambda *args: calls.append(args))
    lab.patch_host(obj, "redis")
    patch = json.loads(calls[0][-1])
    assert patch[:2] == [
        {"op": "test", "path": "/metadata/uid", "value": "uid-a"},
        {"op": "test", "path": "/metadata/resourceVersion", "value": "3"},
    ]
    assert [p for p in patch if p["op"] != "test"] == [
        {"op": "replace", "path": "/spec/template/spec/containers/0/env/0/value", "value": "redis"}
    ]


def test_nonlab_namespace_denied(monkeypatch):
    monkeypatch.setattr(lab, "command", lambda *a, **kw: SimpleNamespace(stdout="rackops\n"))
    monkeypatch.setattr(
        lab, "kube", lambda *a, **kw: SimpleNamespace(stdout='{"metadata":{"labels":{}}}')
    )
    with pytest.raises(RuntimeError, match="identity"):
        lab.guard()


def test_wrong_cluster_denied_before_kubernetes_access(monkeypatch):
    monkeypatch.setattr(lab, "command", lambda *a, **kw: SimpleNamespace(stdout="other\n"))
    monkeypatch.setattr(
        lab, "kube", lambda *a, **kw: pytest.fail("Must not contact another cluster")
    )
    with pytest.raises(RuntimeError, match="does not exist"):
        lab.guard()


def test_concurrent_host_change_denies_recovery(monkeypatch, tmp_path):
    state = tmp_path / "incident.json"
    state.write_text(
        json.dumps(
            {
                "scenario": "bad_redis_host",
                "kind": "deployment",
                "name": "rackops-api",
                "uid": "uid-a",
                "before": "redis",
                "fault": "redis-invalid",
            }
        )
    )
    monkeypatch.setattr(lab, "STATE", state)
    monkeypatch.setattr(lab, "guard", lambda: None)
    monkeypatch.setattr(
        lab,
        "scenario_resource",
        lambda scenario: (
            "deployment",
            "rackops-api",
            {"metadata": {"uid": "uid-a"}},
            lambda obj: ("path", "changed-by-someone-else"),
        ),
    )
    monkeypatch.setattr(
        lab, "patch_host", lambda *a: pytest.fail("Must not overwrite concurrent edit")
    )
    with pytest.raises(RuntimeError, match="Concurrent"):
        lab.recover()
    assert state.exists()


def test_failed_recovery_keeps_snapshot(monkeypatch, tmp_path):
    state = tmp_path / "incident.json"
    state.write_text(
        json.dumps(
            {
                "scenario": "bad_redis_host",
                "kind": "deployment",
                "name": "rackops-api",
                "uid": "uid-a",
                "before": "redis",
                "fault": "redis-invalid",
            }
        )
    )
    monkeypatch.setattr(lab, "STATE", state)
    monkeypatch.setattr(lab, "guard", lambda: None)
    monkeypatch.setattr(
        lab,
        "scenario_resource",
        lambda scenario: (
            "deployment",
            "rackops-api",
            {"metadata": {"uid": "uid-a"}},
            lambda obj: ("path", "redis"),
        ),
    )
    monkeypatch.setattr(lab, "readiness", lambda: None)
    monkeypatch.setattr(lab, "request_check", lambda: {"passed": False})
    with pytest.raises(RuntimeError, match="Recovery failed"):
        lab.recover()
    assert state.exists()


def test_operator_denies_other_resources_and_fields(monkeypatch):
    monkeypatch.setattr(
        lab, "kube", lambda *a, **kw: pytest.fail("Denied action reached Kubernetes")
    )
    with pytest.raises(ValueError):
        lab.named_resource("secret", "credentials")
    with pytest.raises(ValueError):
        lab.patch_field(
            "deployment",
            "redis",
            {"spec": {"replicas": 1}},
            "/spec/template/spec/serviceAccountName",
            "default",
            "admin",
        )


def test_service_port_and_image_repair_use_version_preconditions(monkeypatch):
    calls = []
    monkeypatch.setattr(lab, "kube", lambda *args: calls.append(args))
    service = {
        "metadata": {"uid": "service-a", "resourceVersion": "5"},
        "spec": {"ports": [{"port": 8000, "targetPort": 6553}]},
    }
    path, before = lab.service_port_location(service)
    lab.patch_field("service", "rackops-api", service, path, before, 8000)
    patch = json.loads(calls[-1][-1])
    assert patch[1]["value"] == "5"
    assert patch[-1] == {"op": "replace", "path": "/spec/ports/0/targetPort", "value": 8000}

    app = {
        "metadata": {"uid": "api-a", "resourceVersion": "8"},
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "api",
                            "image": "rackops-api:missing",
                            "env": [{"name": "RACKOPS_REDIS_HOST", "value": "redis"}],
                        }
                    ]
                }
            }
        },
    }
    path, before = lab.image_location(app)
    lab.patch_field("deployment", "rackops-api", app, path, before, "rackops-api:dev")
    assert json.loads(calls[-1][-1])[-1]["path"] == path


def test_healthy_scenario_executes_no_field_mutation(monkeypatch, tmp_path):
    monkeypatch.setattr(lab, "STATE", tmp_path / "incident.json")
    monkeypatch.setattr(lab, "guard", lambda: None)
    monkeypatch.setattr(lab, "request_check", lambda: {"passed": True})
    monkeypatch.setattr(lab, "patch_field", lambda *a: pytest.fail("Healthy case mutated lab"))
    result = lab.inject("healthy")
    assert result["mutation_count"] == 0
    assert not (tmp_path / "incident.json").exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://127.0.0.1",
        "http://127.0.0.1@evil.test",
        "http://localhost/?secret=x",
    ],
)
def test_cli_probes_restricted_to_loopback(url):
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        local_url(url)
