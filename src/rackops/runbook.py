"""Deterministic baseline using ordinary observed state, never scenario truth."""

from dataclasses import dataclass

from rackops.gateway import Gateway, PolicyDenied


@dataclass(frozen=True)
class Observations:
    probe_passed: bool
    rollout_ready: bool
    redis_replicas: int
    service_target_port: int
    container_port: int
    redis_host: str
    prior_redis_hosts: tuple[str, ...]
    image: str
    prior_images: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    status: str
    root_cause: str
    evidence_ids: tuple[str, ...]
    action_id: str | None = None
    reason: str = ""


def decide(observed: Observations) -> tuple[str, str | int | None, str | None]:
    """Return category, proposed value, and repair field from operational clues."""
    if observed.redis_replicas == 0:
        return "unsupported_dependency_outage", None, None
    if not observed.rollout_ready and observed.image not in observed.prior_images:
        if observed.prior_images:
            return "broken_image", observed.prior_images[-1], "image"
        return "unknown", None, None
    if observed.probe_passed and observed.rollout_ready:
        return "healthy", None, None
    if observed.service_target_port != observed.container_port:
        return "bad_service_target_port", observed.container_port, "target_port"
    if observed.redis_host not in observed.prior_redis_hosts:
        if observed.prior_redis_hosts:
            return "bad_dependency_configuration", observed.prior_redis_hosts[-1], "redis_host"
        return "unknown", None, None
    return "unknown", None, None


def run(gateway: Gateway, observed: Observations) -> Decision:
    if not observed.evidence_ids or any(e not in gateway.evidence for e in observed.evidence_ids):
        raise PolicyDenied("Runbook decision needs existing operational evidence")
    category, value, field = decide(observed)
    if category == "healthy":
        return Decision("healthy_no_action", category, observed.evidence_ids)
    if field is None:
        return Decision(
            "escalated",
            category,
            observed.evidence_ids,
            reason="No supported evidence-backed repair",
        )
    kind = "service" if field == "target_port" else "deployment"
    summary = f"Restore {field} using observed configuration or workload history"
    action = gateway.propose(
        kind, "rackops-api", field, value, list(observed.evidence_ids), summary
    )
    gateway.apply(action.id)
    checked = gateway.verify(action.id)
    if checked.status == "verified":
        return Decision("verified_repair", category, observed.evidence_ids, action.id)
    gateway.rollback(action.id)
    return Decision(
        "escalated",
        category,
        observed.evidence_ids,
        action.id,
        reason="Independent checker rejected the repair; rollback verified",
    )
