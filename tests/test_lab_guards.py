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
        json.dumps({"uid": "uid-a", "before_host": "redis", "fault_host": "redis-invalid"})
    )
    monkeypatch.setattr(lab, "STATE", state)
    monkeypatch.setattr(lab, "guard", lambda: None)
    monkeypatch.setattr(lab, "deployment", lambda: {"metadata": {"uid": "uid-a"}})
    monkeypatch.setattr(lab, "host_location", lambda obj: ("path", "changed-by-someone-else"))
    monkeypatch.setattr(
        lab, "patch_host", lambda *a: pytest.fail("Must not overwrite concurrent edit")
    )
    with pytest.raises(RuntimeError, match="Concurrent"):
        lab.recover()
    assert state.exists()


def test_failed_recovery_keeps_snapshot(monkeypatch, tmp_path):
    state = tmp_path / "incident.json"
    state.write_text(
        json.dumps({"uid": "uid-a", "before_host": "redis", "fault_host": "redis-invalid"})
    )
    monkeypatch.setattr(lab, "STATE", state)
    monkeypatch.setattr(lab, "guard", lambda: None)
    monkeypatch.setattr(lab, "deployment", lambda: {"metadata": {"uid": "uid-a"}})
    monkeypatch.setattr(lab, "host_location", lambda obj: ("path", "redis"))
    monkeypatch.setattr(lab, "readiness", lambda: None)
    monkeypatch.setattr(lab, "request_check", lambda: {"passed": False})
    with pytest.raises(RuntimeError, match="Recovery failed"):
        lab.recover()
    assert state.exists()


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
