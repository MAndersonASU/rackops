from dataclasses import replace

import pytest

from rackops.gateway import FieldState, Gateway, PolicyDenied
from rackops.runbook import Observations
from rackops.strategies import FakeProvider, Intent, basic, fake_run_record, structured


class Backend:
    def __init__(self):
        self.field = FieldState(
            "deployment", "rackops-api", "redis_host", "redis-invalid", "api-uid", "1"
        )

    def read_field(self, kind, name, field):
        return self.field

    def change_field(self, before, value):
        self.field = replace(before, value=value, resource_version="2")
        return self.field


def setup():
    backend = Backend()
    gateway = Gateway(backend, lambda: {"passed": True})
    e1 = gateway.add_evidence("probe", "Writes failed")
    e2 = gateway.add_evidence("deployment", "Previous host was redis")
    observed = Observations(
        False,
        False,
        1,
        8000,
        8000,
        "redis-invalid",
        ("redis",),
        "rackops-api:dev",
        (),
        (e1.id, e2.id),
    )
    return backend, gateway, observed


def test_structured_fixture_requires_citations_and_repairs():
    backend, gateway, observed = setup()
    provider = FakeProvider(
        [
            Intent(
                "repair",
                "bad_dependency_configuration",
                "Restore observed prior host",
                "deployment",
                "redis_host",
                "redis",
                observed.evidence_ids,
            )
        ]
    )
    decision = structured(gateway, observed, provider)
    assert decision.status == "verified_repair"
    assert backend.field.value == "redis"
    record = fake_run_record("structured", decision, provider)
    assert record["benchmark_eligible"] is False
    assert record["model_id"] == "fixture-scripted-v1"
    assert record["api_cost_usd"] == 0


def test_basic_can_make_false_healthy_claim_for_later_scoring():
    _, gateway, observed = setup()
    provider = FakeProvider([Intent("healthy", "none", "Looks fine")])
    assert basic(gateway, observed, provider).status == "claimed_healthy"
    with pytest.raises(PolicyDenied, match="contradicts"):
        structured(
            gateway,
            observed,
            FakeProvider(
                [Intent("healthy", "none", "Looks fine", evidence_ids=observed.evidence_ids)]
            ),
        )


def test_structured_rejects_fabricated_or_single_source_evidence():
    _, gateway, observed = setup()
    repair = Intent(
        "repair",
        "bad_dependency_configuration",
        "Restore host",
        "deployment",
        "redis_host",
        "redis",
        ("E9999",),
    )
    with pytest.raises(PolicyDenied, match="evidence"):
        structured(gateway, observed, FakeProvider([repair]))
    one_source = replace(repair, evidence_ids=(observed.evidence_ids[0],))
    with pytest.raises(PolicyDenied, match="two independent"):
        structured(gateway, observed, FakeProvider([one_source]))


def test_unsupported_case_cannot_be_mutated_by_structured_strategy():
    backend, gateway, observed = setup()
    observed = replace(observed, redis_replicas=0)
    provider = FakeProvider(
        [
            Intent(
                "repair",
                "dependency_outage",
                "Try host",
                "deployment",
                "redis_host",
                "redis",
                observed.evidence_ids,
            )
        ]
    )
    with pytest.raises(PolicyDenied, match="No approved"):
        structured(gateway, observed, provider)
    assert backend.field.value == "redis-invalid"
