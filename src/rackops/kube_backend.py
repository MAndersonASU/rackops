"""Restricted in-cluster Kubernetes adapter for the runtime gateway.

This adapter uses a namespaced ServiceAccount. It never starts a subprocess,
reads a host kubeconfig, or receives a Docker socket.
"""

import json
import math
import os
from pathlib import Path
from urllib.parse import quote

import httpx

from rackops.checker import request_pair, summarize
from rackops.gateway import (
    CONTEXT,
    FIELDS,
    NAMESPACE,
    FieldState,
    Gateway,
    PolicyDenied,
    validate_value,
)
from rackops.runbook import Observations

TOKEN_ROOT = Path("/var/run/secrets/kubernetes.io/serviceaccount")


class KubeBackend:
    def __init__(
        self,
        client: httpx.Client,
        *,
        namespace=NAMESPACE,
        context=CONTEXT,
        application_client: httpx.Client | None = None,
        metrics_client: httpx.Client | None = None,
    ):
        if namespace != NAMESPACE or context != CONTEXT:
            raise PolicyDenied("Runtime must run in the explicit RackOps lab")
        self.client = client
        self.namespace = namespace
        self.context = context
        self.application_client = application_client or httpx.Client(
            base_url="http://rackops-api:8000",
            timeout=2,
            trust_env=False,
            follow_redirects=False,
        )
        self.metrics_client = metrics_client or httpx.Client(
            base_url="http://prometheus:9090",
            timeout=2,
            trust_env=False,
            follow_redirects=False,
        )
        self._owns_application_client = application_client is None
        self._owns_metrics_client = metrics_client is None

    @classmethod
    def from_incluster(cls):
        host = os.getenv("KUBERNETES_SERVICE_HOST")
        port = os.getenv("KUBERNETES_SERVICE_PORT_HTTPS", "443")
        if not host or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise PolicyDenied("Missing in-cluster Kubernetes API coordinates")
        if not host.replace(".", "").replace(":", "").isalnum():
            raise PolicyDenied("Invalid in-cluster Kubernetes API host")
        if (TOKEN_ROOT / "namespace").read_text(encoding="utf-8").strip() != NAMESPACE:
            raise PolicyDenied("ServiceAccount token is outside the lab namespace")
        token = (TOKEN_ROOT / "token").read_text(encoding="utf-8").strip()
        if not token or len(token) > 8192:
            raise PolicyDenied("Invalid projected ServiceAccount token")
        client = httpx.Client(
            base_url=f"https://{host}:{port}",
            headers={"Authorization": f"Bearer {token}"},
            verify=str(TOKEN_ROOT / "ca.crt"),
            timeout=3,
            trust_env=False,
            follow_redirects=False,
        )
        backend = cls(client)
        backend.verify_lab_marker()
        return backend

    def close(self):
        self.client.close()
        if self._owns_application_client:
            self.application_client.close()
        if self._owns_metrics_client:
            self.metrics_client.close()

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self.client.request(method, path, **kwargs)
            response.raise_for_status()
            result = response.json()
            if type(result) is not dict:
                raise ValueError("Unexpected API response")
            return result
        except (httpx.HTTPError, ValueError):
            # Never echo request headers, token, kubeconfig paths, or response bodies.
            raise RuntimeError("Kubernetes API operation failed or returned invalid JSON") from None

    def _path(self, kind: str, name: str) -> str:
        if (kind, name) in {("deployment", "rackops-api"), ("deployment", "redis")}:
            return f"/apis/apps/v1/namespaces/{NAMESPACE}/deployments/{name}"
        if (kind, name) == ("service", "rackops-api"):
            return f"/api/v1/namespaces/{NAMESPACE}/services/{name}"
        raise PolicyDenied("Kubernetes resource outside runtime allowlist")

    def verify_lab_marker(self):
        marker = self._request("GET", f"/api/v1/namespaces/{NAMESPACE}/configmaps/rackops-identity")
        if (
            marker.get("data", {}).get("cluster") != "rackops"
            or marker.get("metadata", {}).get("namespace") != NAMESPACE
        ):
            raise PolicyDenied("Lab identity marker does not match")

    def _resource(self, kind: str, name: str) -> dict:
        obj = self._request("GET", self._path(kind, name))
        meta = obj.get("metadata", {})
        if (
            meta.get("namespace") != NAMESPACE
            or meta.get("name") != name
            or meta.get("labels", {}).get("rackops.io/lab") != "rackops"
            or not meta.get("uid")
            or not meta.get("resourceVersion")
        ):
            raise PolicyDenied("Unexpected resource identity")
        return obj

    def _field(self, obj: dict, kind: str, name: str, field: str) -> tuple[str, str | int]:
        if (kind, name, field) not in FIELDS:
            raise PolicyDenied("Field outside runtime allowlist")
        if kind == "service":
            ports = obj["spec"]["ports"]
            if len(ports) != 1 or ports[0]["port"] != 8000:
                raise PolicyDenied("Unexpected Service port layout")
            value = ports[0]["targetPort"]
            path = "/spec/ports/0/targetPort"
        else:
            containers = obj["spec"]["template"]["spec"]["containers"]
            if len(containers) != 1 or containers[0]["name"] != "api":
                raise PolicyDenied("Unexpected Deployment container layout")
            if field == "image":
                value = containers[0]["image"]
                path = "/spec/template/spec/containers/0/image"
            else:
                env = containers[0]["env"]
                matches = [
                    (i, item)
                    for i, item in enumerate(env)
                    if item["name"] == "RACKOPS_REDIS_HOST" and "value" in item
                ]
                if len(matches) != 1:
                    raise PolicyDenied("Redis host configuration is ambiguous")
                index, item = matches[0]
                value = item["value"]
                path = f"/spec/template/spec/containers/0/env/{index}/value"
        validate_value(field, value)
        return path, value

    def read_field(self, kind: str, name: str, field: str) -> FieldState:
        obj = self._resource(kind, name)
        _, value = self._field(obj, kind, name, field)
        meta = obj["metadata"]
        return FieldState(kind, name, field, value, meta["uid"], meta["resourceVersion"])

    def change_field(self, before: FieldState, value: str | int) -> FieldState:
        if (before.kind, before.name, before.field) not in FIELDS:
            raise PolicyDenied("Mutation target outside runtime allowlist")
        if before.context != CONTEXT or before.namespace != NAMESPACE:
            raise PolicyDenied("Mutation context or namespace mismatch")
        validate_value(before.field, value)
        obj = self._resource(before.kind, before.name)
        path, current = self._field(obj, before.kind, before.name, before.field)
        meta = obj["metadata"]
        if (meta["uid"], meta["resourceVersion"], current) != (
            before.uid,
            before.resource_version,
            before.value,
        ):
            raise PolicyDenied("Mutation preconditions are stale")
        patch = [
            {"op": "test", "path": "/metadata/uid", "value": before.uid},
            {"op": "test", "path": "/metadata/resourceVersion", "value": before.resource_version},
            {"op": "test", "path": path, "value": before.value},
            {"op": "replace", "path": path, "value": value},
        ]
        response = self._request(
            "PATCH",
            self._path(before.kind, before.name),
            json=patch,
            headers={"Content-Type": "application/json-patch+json"},
        )
        metadata = response.get("metadata", {})
        if (
            metadata.get("uid") != before.uid
            or metadata.get("namespace") != NAMESPACE
            or metadata.get("labels", {}).get("rackops.io/lab") != "rackops"
        ):
            raise PolicyDenied("Patched resource identity mismatch")
        _, confirmed = self._field(response, before.kind, before.name, before.field)
        if confirmed != value or not metadata.get("resourceVersion"):
            raise PolicyDenied("Patch did not confirm the approved field")
        return FieldState(
            before.kind,
            before.name,
            before.field,
            confirmed,
            before.uid,
            metadata["resourceVersion"],
        )

    def read_events(self, *, limit=20) -> str:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise PolicyDenied("Event limit must be 1..50")
        data = self._request(
            "GET", f"/api/v1/namespaces/{NAMESPACE}/events", params={"limit": limit}
        )
        lines = []
        for event in data.get("items", [])[:limit]:
            ref = event.get("involvedObject", {})
            if ref.get("name") not in {"rackops-api", "redis"} and not ref.get(
                "name", ""
            ).startswith(("rackops-api-", "redis-")):
                continue
            lines.append(f"{event.get('reason', '')}: {event.get('message', '')}"[:300])
        return "\n".join(lines)[:2000]

    def read_logs(self, *, limit=30) -> str:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise PolicyDenied("Log line limit must be 1..100")
        pods = self._request(
            "GET",
            f"/api/v1/namespaces/{NAMESPACE}/pods",
            params={"labelSelector": "app=rackops-api", "limit": 20},
        )
        items = [
            pod
            for pod in pods.get("items", [])
            if pod.get("metadata", {}).get("labels", {}).get("rackops.io/lab") == "rackops"
        ]
        if not items:
            return ""
        name = items[0]["metadata"]["name"]
        if not name.startswith("rackops-api-"):
            raise PolicyDenied("Unexpected application Pod identity")
        try:
            response = self.client.get(
                f"/api/v1/namespaces/{NAMESPACE}/pods/{quote(name)}/log",
                params={"container": "api", "tailLines": limit, "limitBytes": 2000},
            )
            response.raise_for_status()
            return response.text[:2000]
        except httpx.HTTPError:
            raise RuntimeError("Bounded application log read failed") from None

    def probe_application(self) -> dict:
        """Two real writes and reads; a short diagnostic, not final recovery proof."""
        import uuid

        key = "observe-" + uuid.uuid4().hex[:16]
        return summarize(request_pair(self.application_client, key, key))

    def query_request_metrics(self, *, window_seconds=60) -> float | None:
        if window_seconds not in {30, 60, 120}:
            raise PolicyDenied("Metrics window must be 30, 60, or 120 seconds")
        query = (
            f'sum(rate(rackops_http_requests_total{{route="/items/{{key}}"}}[{window_seconds}s]))'
        )
        try:
            response = self.metrics_client.get("/api/v1/query", params={"query": query})
            response.raise_for_status()
            data = response.json()
            results = data.get("data", {}).get("result", [])
            if not results:
                return None
            value = float(results[0]["value"][1])
            if not math.isfinite(value) or value < 0:
                raise ValueError("Invalid metric")
            return value
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            raise RuntimeError("Bounded Prometheus query failed") from None

    def deployment_history(self, uid: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        replicasets = self._request(
            "GET",
            f"/apis/apps/v1/namespaces/{NAMESPACE}/replicasets",
            params={"labelSelector": "app=rackops-api", "limit": 20},
        )
        histories = []
        for item in replicasets.get("items", []):
            metadata = item.get("metadata", {})
            if metadata.get("namespace") != NAMESPACE or not any(
                ref.get("uid") == uid for ref in metadata.get("ownerReferences", [])
            ):
                continue
            containers = (
                item.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
            )
            if len(containers) != 1 or containers[0].get("name") != "api":
                continue
            hosts = [
                entry.get("value")
                for entry in containers[0].get("env", [])
                if entry.get("name") == "RACKOPS_REDIS_HOST"
            ]
            if len(hosts) != 1:
                continue
            revision = metadata.get("annotations", {}).get("deployment.kubernetes.io/revision", "0")
            if not revision.isdigit():
                continue
            histories.append((int(revision), hosts[0], containers[0].get("image")))
        histories.sort(key=lambda row: row[0])
        return tuple(row[1] for row in histories), tuple(row[2] for row in histories)

    def observe_for_runbook(self, gateway: Gateway) -> Observations:
        """Collect bounded operational clues and their original evidence IDs."""
        app = self._resource("deployment", "rackops-api")
        redis = self._resource("deployment", "redis")
        service = self._resource("service", "rackops-api")
        _, host = self._field(app, "deployment", "rackops-api", "redis_host")
        _, image = self._field(app, "deployment", "rackops-api", "image")
        _, target_port = self._field(service, "service", "rackops-api", "target_port")
        container_port = app["spec"]["template"]["spec"]["containers"][0]["ports"][0][
            "containerPort"
        ]
        if type(container_port) is not int or not 1 <= container_port <= 65535:
            raise PolicyDenied("Unexpected container port")
        redis_replicas = redis["spec"]["replicas"]
        if type(redis_replicas) is not int or not 0 <= redis_replicas <= 1:
            raise PolicyDenied("Unexpected Redis replica count")
        desired = app["spec"].get("replicas", 1)
        status = app.get("status", {})
        ready = (
            status.get("observedGeneration", 0) >= app["metadata"].get("generation", 0)
            and status.get("updatedReplicas", 0) == desired
            and status.get("availableReplicas", 0) == desired
        )
        prior_hosts, prior_images = self.deployment_history(app["metadata"]["uid"])
        prior_hosts = tuple(h for h in prior_hosts if h != host)
        prior_images = tuple(i for i in prior_images if i != image)
        probe = self.probe_application()
        metrics = self.query_request_metrics(window_seconds=60)
        try:
            events = self.read_events(limit=20)
        except RuntimeError:
            events = "Events unavailable"
        try:
            logs = self.read_logs(limit=30)
        except RuntimeError:
            logs = "Logs unavailable"
        evidence = [
            gateway.add_evidence(
                "deployment",
                json.dumps(
                    {
                        "image": image,
                        "redis_host": host,
                        "container_port": container_port,
                        "rollout_ready": ready,
                        "resource_version": app["metadata"]["resourceVersion"],
                    }
                ),
            ),
            gateway.add_evidence("service", json.dumps({"target_port": target_port})),
            gateway.add_evidence("deployment", json.dumps({"redis_replicas": redis_replicas})),
            gateway.add_evidence(
                "deployment",
                json.dumps(
                    {
                        "previous_hosts": prior_hosts,
                        "previous_images": prior_images,
                    }
                ),
            ),
            gateway.add_evidence("probe", json.dumps(probe)),
            gateway.add_evidence("metrics", json.dumps({"request_rate_per_second": metrics})),
            gateway.add_evidence("events", events[:2000]),
            gateway.add_evidence("logs", logs[:2000]),
        ]
        return Observations(
            probe["passed"],
            ready,
            redis_replicas,
            target_port,
            container_port,
            host,
            prior_hosts,
            image,
            prior_images,
            tuple(item.id for item in evidence),
        )
