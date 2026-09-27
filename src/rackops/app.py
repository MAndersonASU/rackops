"""Small Redis-backed API. Fixture injection is available only to Python tests."""

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, ConfigDict, Field
from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

logger = logging.getLogger("rackops.application")
Key = Annotated[str, Path(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]


class Value(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: str = Field(min_length=1, max_length=1024)


def create_app(redis_client=None) -> FastAPI:
    client = (
        redis_client
        if redis_client is not None
        else Redis(
            host=os.getenv("RACKOPS_REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("RACKOPS_REDIS_PORT", "6379")),
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            retry=Retry(NoBackoff(), 0),
        )
    )
    registry = CollectorRegistry()
    requests = Counter(
        "rackops_http_requests_total",
        "API requests",
        ["method", "route", "status"],
        registry=registry,
    )
    latency = Histogram(
        "rackops_http_request_seconds",
        "API request latency",
        ["method", "route"],
        registry=registry,
    )

    @asynccontextmanager
    async def lifespan(_app):
        yield
        client.close()

    app = FastAPI(title="RackOps disposable lab API", lifespan=lifespan)

    @app.middleware("http")
    async def instrument(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        # Route templates prevent arbitrary keys/paths creating unbounded label cardinality.
        route = getattr(request.scope.get("route"), "path", "unmatched")
        if route != "/metrics":
            method = request.method if request.method in {"GET", "PUT"} else "OTHER"
            requests.labels(method, route, response.status_code).inc()
            latency.labels(method, route).observe(time.perf_counter() - start)
        return response

    @app.exception_handler(RedisError)
    async def redis_error(_request, exc):
        from fastapi.responses import JSONResponse

        # Keep exception text, connection strings, and stored values out of logs.
        logger.warning("dependency=redis operation_failed error_type=%s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": "Redis dependency unavailable"})

    @app.get("/livez")
    def livez():
        return {"status": "alive"}

    @app.get("/readyz")
    def readyz():
        client.ping()
        return {"status": "ready"}

    @app.put("/items/{key}")
    def put_item(key: Key, body: Value):
        client.set(f"rackops:{key}", body.value, ex=120)
        return {"key": key, "value": body.value}

    @app.get("/items/{key}")
    def get_item(key: Key):
        value = client.get(f"rackops:{key}")
        if value is None:
            raise HTTPException(status_code=404, detail="Item not found")
        return {"key": key, "value": value}

    @app.get("/metrics")
    def metrics():
        return Response(
            content=generate_latest(registry), headers={"Content-Type": CONTENT_TYPE_LATEST}
        )

    return app
