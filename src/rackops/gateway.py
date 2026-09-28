"""Small policy core for a future agent's typed tools.

An actual Kubernetes adapter and restricted service account are still required
before any runtime agent can use this against the lab. This module never calls
the trusted test runner or reads its scenario truth.
"""

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

CONTEXT = "kind-rackops"
NAMESPACE = "rackops-lab"
FIELDS = {
    ("deployment", "rackops-api", "redis_host"),
    ("deployment", "rackops-api", "image"),
    ("service", "rackops-api", "target_port"),
}
SOURCES = {"logs", "events", "deployment", "service", "metrics", "probe"}
MAX_EVIDENCE_CHARS = 2000


class PolicyDenied(ValueError):
    """A proposed runtime-agent operation is outside the lab policy."""


@dataclass(frozen=True)
class FieldState:
    kind: str
    name: str
    field: str
    value: str | int
    uid: str
    resource_version: str
    context: str = CONTEXT
    namespace: str = NAMESPACE


class Backend(Protocol):
    def read_field(self, kind: str, name: str, field: str) -> FieldState: ...

    def change_field(self, before: FieldState, value: str | int) -> FieldState: ...


@dataclass(frozen=True)
class Evidence:
    id: str
    observed_at: str
    source: str
    content: str


@dataclass
class Action:
    id: str
    kind: str
    name: str
    field: str
    before: FieldState
    proposed_value: str | int
    evidence_ids: tuple[str, ...]
    decision: str
    status: str = "proposed"
    after: FieldState | None = None
    rollback_status: str = "not_requested"


def validate_value(field: str, value):
    if field == "redis_host":
        valid = type(value) is str and bool(re.fullmatch(r"[a-z][a-z0-9-]{0,62}", value))
    elif field == "image":
        valid = type(value) is str and bool(
            re.fullmatch(r"rackops-api:[a-zA-Z0-9_.-]{1,64}", value)
        )
    elif field == "target_port":
        valid = type(value) is int and 1 <= value <= 65535
    else:
        valid = False
    if not valid:
        raise PolicyDenied("Invalid approved-field value")


class Gateway:
    def __init__(
        self,
        backend: Backend,
        checker: Callable[[], dict],
        *,
        max_calls=15,
        max_repairs=2,
        max_seconds=300,
        record_path: Path | None = None,
    ):
        if not 1 <= max_calls <= 50 or not 1 <= max_repairs <= 5 or not 1 <= max_seconds <= 600:
            raise ValueError("Invalid execution limits")
        self.backend = backend
        self.checker = checker
        self.max_calls = max_calls
        self.max_repairs = max_repairs
        self.max_seconds = max_seconds
        self.record_path = record_path
        self.started = time.monotonic()
        self.calls = 0
        self.repairs = 0
        self.evidence: dict[str, Evidence] = {}
        self.actions: dict[str, Action] = {}
        self.pending: str | None = None
        self.failed_signatures: set[tuple[str, str, str, str]] = set()

    def record(self, event: str, details: dict):
        if self.record_path is None:
            return
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"at": datetime.now(UTC).isoformat(), "event": event, **details}
        with self.record_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")

    def count_call(self):
        if time.monotonic() - self.started >= self.max_seconds:
            raise PolicyDenied("Incident time budget exhausted")
        if self.calls >= self.max_calls:
            raise PolicyDenied("Tool-call budget exhausted")
        self.calls += 1

    def add_evidence(self, source: str, content: str) -> Evidence:
        self.count_call()
        if source not in SOURCES or type(content) is not str or len(content) > MAX_EVIDENCE_CHARS:
            raise PolicyDenied("Invalid evidence source or size")
        evidence = Evidence(
            f"E{len(self.evidence) + 1:04d}",
            datetime.now(UTC).isoformat(),
            source,
            content,
        )
        self.evidence[evidence.id] = evidence
        self.record("evidence", asdict(evidence))
        return evidence

    def propose(
        self, kind: str, name: str, field: str, value, evidence_ids: list[str], decision: str
    ) -> Action:
        self.count_call()
        if (kind, name, field) not in FIELDS:
            raise PolicyDenied("Resource or field is outside the runtime allowlist")
        validate_value(field, value)
        if (
            not evidence_ids
            or len(evidence_ids) > 8
            or any(e not in self.evidence for e in evidence_ids)
            or len(set(evidence_ids)) != len(evidence_ids)
        ):
            raise PolicyDenied("Action requires distinct existing evidence IDs")
        if type(decision) is not str or not 1 <= len(decision) <= 240:
            raise PolicyDenied("Action requires a short decision summary")
        if self.pending is not None or self.repairs >= self.max_repairs:
            raise PolicyDenied("A change is pending or repair budget exhausted")
        before = self.backend.read_field(kind, name, field)
        if (before.kind, before.name, before.field) != (kind, name, field):
            raise PolicyDenied("Backend returned the wrong field")
        if (
            before.context != CONTEXT
            or before.namespace != NAMESPACE
            or not before.uid
            or not before.resource_version
        ):
            raise PolicyDenied("Lab resource identity check failed")
        if value == before.value:
            raise PolicyDenied("No-op mutations are denied")
        signature = (kind, name, field, str(value))
        if signature in self.failed_signatures:
            raise PolicyDenied("Repeated identical failed repair is denied")
        action = Action(
            f"A{len(self.actions) + 1:04d}",
            kind,
            name,
            field,
            before,
            value,
            tuple(evidence_ids),
            decision,
        )
        self.actions[action.id] = action
        self.record("proposed", {"action": asdict(action)})
        return action

    def apply(self, action_id: str) -> Action:
        self.count_call()
        action = self.actions.get(action_id)
        if action is None or action.status != "proposed":
            raise PolicyDenied("Unknown or already applied proposal")
        if self.pending is not None or self.repairs >= self.max_repairs:
            raise PolicyDenied("A change is pending or repair budget exhausted")
        current = self.backend.read_field(action.kind, action.name, action.field)
        if current != action.before:
            raise PolicyDenied("Resource changed since proposal; re-observe before repair")
        self.repairs += 1
        self.pending = action_id
        try:
            after = self.backend.change_field(current, action.proposed_value)
            if (after.kind, after.name, after.field, after.uid, after.context, after.namespace) != (
                current.kind,
                current.name,
                current.field,
                current.uid,
                CONTEXT,
                NAMESPACE,
            ) or after.value != action.proposed_value:
                raise PolicyDenied("Backend did not confirm the approved field change")
            action.after = after
            action.status = "applied_pending_verification"
            self.record("applied", {"action": asdict(action)})
        except Exception:
            # A transport failure can occur after a server-side patch. Freeze
            # mutations until an operator inspects the uncertain state.
            action.status = "apply_uncertain"
            self.failed_signatures.add(
                (action.kind, action.name, action.field, str(action.proposed_value))
            )
            self.record("apply_failed", {"action": asdict(action)})
            raise
        return action

    def verify(self, action_id: str) -> Action:
        """The checker is injected by trusted runner code, not the agent."""
        action = self.actions.get(action_id)
        if (
            action is None
            or action_id != self.pending
            or action.status != "applied_pending_verification"
        ):
            raise PolicyDenied("No matching pending action")
        independent_result = self.checker()
        if type(independent_result.get("passed")) is not bool:
            raise PolicyDenied("Invalid independent verification result")
        self.record("verification", {"action_id": action_id, "result": independent_result})
        if independent_result["passed"]:
            action.status = "verified"
            self.pending = None
        else:
            action.status = "verification_failed"
            self.failed_signatures.add(
                (action.kind, action.name, action.field, str(action.proposed_value))
            )
        return action

    def rollback(self, action_id: str) -> Action:
        # Safety rollback stays available after the agent's call/time budget.
        action = self.actions.get(action_id)
        if action is None or action_id != self.pending or action.status != "verification_failed":
            raise PolicyDenied("Only a failed pending repair may be rolled back")
        current = self.backend.read_field(action.kind, action.name, action.field)
        if current != action.after:
            action.rollback_status = "conflict"
            self.record("rollback_conflict", {"action_id": action_id})
            raise PolicyDenied("Concurrent change prevents safe rollback")
        try:
            restored = self.backend.change_field(current, action.before.value)
            if (
                restored.value != action.before.value
                or restored.uid != action.before.uid
                or restored.context != CONTEXT
                or restored.namespace != NAMESPACE
            ):
                raise PolicyDenied("Rollback was not independently read back")
            read_back = self.backend.read_field(action.kind, action.name, action.field)
            if read_back != restored:
                raise PolicyDenied("Rollback read-back verification failed")
            action.rollback_status = "verified"
            action.status = "rolled_back"
            self.pending = None
            self.record("rolled_back", {"action": asdict(action)})
        except Exception:
            action.rollback_status = "failed"
            self.record("rollback_failed", {"action": asdict(action)})
            raise
        return action
