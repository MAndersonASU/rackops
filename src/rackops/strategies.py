"""Offline strategy loops. Hosted-model transport remains a later milestone."""

from dataclasses import asdict, dataclass
from typing import Protocol

from rackops.gateway import Gateway, PolicyDenied
from rackops.runbook import Decision, Observations


@dataclass(frozen=True)
class Intent:
    choice: str  # repair, healthy, or escalate
    root_cause: str
    decision: str
    kind: str | None = None
    field: str | None = None
    value: str | int | None = None
    evidence_ids: tuple[str, ...] = ()


class Provider(Protocol):
    model_id: str

    def choose(self, observed: Observations) -> Intent: ...


class FakeProvider:
    """Scripted test double. Its outputs are never eligible for benchmarks."""

    model_id = "fixture-scripted-v1"

    def __init__(self, intents: list[Intent]):
        self.intents = list(intents)
        self.index = 0

    def choose(self, observed: Observations) -> Intent:
        if self.index >= len(self.intents):
            return Intent("escalate", "unknown", "Scripted fixture exhausted")
        intent = self.intents[self.index]
        self.index += 1
        return intent


def _repair(gateway: Gateway, intent: Intent, references: tuple[str, ...]) -> Decision:
    if intent.kind not in {"deployment", "service"} or intent.field is None:
        raise PolicyDenied("Repair intent lacks an approved target")
    action = gateway.propose(
        intent.kind, "rackops-api", intent.field, intent.value, list(references), intent.decision
    )
    gateway.apply(action.id)
    result = gateway.verify(action.id)
    if result.status == "verified":
        return Decision("verified_repair", intent.root_cause, references, action.id)
    gateway.rollback(action.id)
    return Decision(
        "escalated",
        intent.root_cause,
        references,
        action.id,
        reason="Independent checker rejected the repair; rollback verified",
    )


def basic(gateway: Gateway, observed: Observations, provider: Provider) -> Decision:
    """One plain observe/act turn. Outer gateway safety still applies."""
    intent = provider.choose(observed)
    if intent.choice == "healthy":
        return Decision("claimed_healthy", intent.root_cause, observed.evidence_ids)
    if intent.choice == "escalate":
        return Decision(
            "escalated", intent.root_cause, observed.evidence_ids, reason=intent.decision
        )
    if intent.choice != "repair":
        raise PolicyDenied("Unknown provider decision")
    # The basic strategy does not require model-selected citations. It receives
    # the same operational observations and outer field/action restrictions.
    return _repair(gateway, intent, observed.evidence_ids)


def structured(gateway: Gateway, observed: Observations, provider: Provider) -> Decision:
    """Require explicit evidence and state checks before proposing a repair."""
    gateway.record("state", {"name": "observe"})
    intent = provider.choose(observed)
    gateway.record("state", {"name": "hypothesis", "summary": intent.decision})
    refs = intent.evidence_ids
    if (
        not refs
        or len(refs) > 8
        or len(set(refs)) != len(refs)
        or any(item not in gateway.evidence for item in refs)
    ):
        raise PolicyDenied("Structured diagnosis needs actual distinct evidence IDs")
    if not intent.root_cause or not intent.decision:
        raise PolicyDenied("Structured diagnosis needs a concise cause and summary")
    if intent.choice == "healthy":
        if not observed.probe_passed or not observed.rollout_ready:
            raise PolicyDenied("Healthy conclusion contradicts observed checks")
        gateway.record("state", {"name": "resolve_healthy", "evidence_ids": refs})
        return Decision("healthy_no_action", intent.root_cause, refs)
    if intent.choice == "escalate":
        gateway.record("state", {"name": "escalate", "evidence_ids": refs})
        return Decision("escalated", intent.root_cause, refs, reason=intent.decision)
    if intent.choice != "repair" or observed.redis_replicas == 0:
        raise PolicyDenied("No approved structured repair for this state")
    if len({gateway.evidence[item].source for item in refs}) < 2:
        raise PolicyDenied("Repair hypothesis needs two independent evidence sources")
    gateway.record("state", {"name": "propose", "evidence_ids": refs})
    decision = _repair(gateway, intent, refs)
    gateway.record("state", {"name": decision.status, "action_id": decision.action_id})
    return decision


def fake_run_record(strategy: str, decision: Decision, provider: Provider) -> dict:
    if strategy not in {"basic", "structured"}:
        raise ValueError("Unknown fixture strategy")
    return {
        "execution_mode": "fake_provider",
        "benchmark_eligible": False,
        "strategy": strategy,
        "model_id": provider.model_id,
        "input_tokens": 0,
        "output_tokens": 0,
        "api_cost_usd": 0,
        "decision": asdict(decision),
    }
