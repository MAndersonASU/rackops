from dataclasses import replace

import pytest

from rackops.gateway import FieldState, Gateway, PolicyDenied
from rackops.runbook import Observations, run


class FieldsBackend:
    def __init__(self):
        self.fields = {
            ("deployment", "rackops-api", "redis_host"): "redis-invalid",
            ("deployment", "rackops-api", "image"): "rackops-api:missing",
            ("service", "rackops-api", "target_port"): 6553,
        }
        self.versions = {key: 1 for key in self.fields}
        self.changes = []

    def read_field(self, kind, name, field):
        key = (kind, name, field)
        return FieldState(kind, name, field, self.fields[key], str(key), str(self.versions[key]))

    def change_field(self, before, value):
        key = (before.kind, before.name, before.field)
        if self.read_field(*key) != before:
            raise PolicyDenied("Stale change")
        self.fields[key] = value
        self.versions[key] += 1
        self.changes.append((key, value))
        return self.read_field(*key)


@pytest.fixture
def observed():
    return Observations(
        False,
        True,
        1,
        8000,
        8000,
        "redis-invalid",
        ("redis",),
        "rackops-api:dev",
        ("rackops-api:dev",),
        ("E0001",),
        False,
        True,
    )


def make_gateway(backend, passed=True):
    gateway = Gateway(backend, lambda: {"passed": passed})
    gateway.add_evidence("probe", "Actual request checks")
    return gateway


def test_bad_dependency_repaired_from_history(observed):
    backend = FieldsBackend()
    gateway = make_gateway(backend)
    decision = run(gateway, observed)
    assert decision.root_cause == "bad_dependency_configuration"
    assert decision.status == "verified_repair"
    assert backend.fields[("deployment", "rackops-api", "redis_host")] == "redis"


def test_unready_redis_host_fault_does_not_require_prior_image(observed):
    backend = FieldsBackend()
    gateway = make_gateway(backend)
    decision = run(
        gateway,
        replace(observed, rollout_ready=False, prior_images=()),
    )
    assert decision.root_cause == "bad_dependency_configuration"
    assert decision.status == "verified_repair"


def test_stale_image_history_does_not_override_current_redis_failure(observed):
    backend = FieldsBackend()
    gateway = make_gateway(backend)
    decision = run(
        gateway,
        replace(
            observed,
            rollout_ready=False,
            prior_images=("rackops-api:missing",),
            image_pull_failure=False,
            redis_failure_observed=True,
        ),
    )
    assert decision.root_cause == "bad_dependency_configuration"
    assert backend.fields[("deployment", "rackops-api", "redis_host")] == "redis"


def test_wrong_service_port_uses_observed_container_port(observed):
    backend = FieldsBackend()
    gateway = make_gateway(backend)
    decision = run(gateway, replace(observed, service_target_port=6553, redis_host="redis"))
    assert decision.root_cause == "bad_service_target_port"
    assert backend.fields[("service", "rackops-api", "target_port")] == 8000


def test_failed_rollout_repaired_even_if_old_revision_serves(observed):
    backend = FieldsBackend()
    gateway = make_gateway(backend)
    decision = run(
        gateway,
        replace(
            observed,
            probe_passed=True,
            rollout_ready=False,
            image="rackops-api:missing",
            image_pull_failure=True,
            redis_failure_observed=False,
        ),
    )
    assert decision.root_cause == "broken_image"
    assert backend.fields[("deployment", "rackops-api", "image")] == "rackops-api:dev"


def test_healthy_and_unsupported_exclude_mutation(observed):
    backend = FieldsBackend()
    gateway = make_gateway(backend)
    healthy = run(gateway, replace(observed, probe_passed=True, redis_host="redis"))
    unsupported = run(gateway, replace(observed, redis_replicas=0))
    assert healthy.status == "healthy_no_action"
    assert unsupported.status == "escalated"
    assert unsupported.root_cause == "unsupported_dependency_outage"
    assert backend.changes == []


def test_failed_repair_is_rolled_back_without_false_recovery(observed):
    backend = FieldsBackend()
    gateway = make_gateway(backend, passed=False)
    decision = run(gateway, observed)
    assert decision.status == "escalated"
    assert gateway.actions[decision.action_id].rollback_status == "verified"
    assert backend.fields[("deployment", "rackops-api", "redis_host")] == "redis-invalid"


def test_missing_history_and_missing_evidence_cannot_claim_repair(observed):
    backend = FieldsBackend()
    gateway = make_gateway(backend)
    unknown = run(gateway, replace(observed, prior_redis_hosts=()))
    assert unknown.status == "escalated"
    assert backend.changes == []
    with pytest.raises(PolicyDenied):
        run(gateway, replace(observed, evidence_ids=("E9999",)))
