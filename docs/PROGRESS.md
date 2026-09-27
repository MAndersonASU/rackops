# RackOps progress

## Current milestone

2026-09-27: milestone 1 implementation, with the first scripted dependency
incident prepared. **Milestone 1 is not yet accepted:** real Redis, container
build, Kubernetes readiness, and Prometheus scraping have not been run.

## Environment facts

- Dedicated repository created; branch `main`; no remote or publication.
- Git 2.55.0 available. Python 3.12.14 from the desktop's bundled runtime used
  to create a project-local `.venv`; no system Python installation performed.
- Approximately 31.5 GiB total RAM, 4.2 GiB free, 685.7 GiB free disk at discovery.
- Docker Desktop and WSL processes are running. Docker exists in its per-user
  installation, outside PATH. Execution and directory reads return access denied,
  even after a folder-read permission grant. Linux container support is unverified.
- `kind` and `kubectl` not on PATH. WSL status/list return access denied.
- GitHub CLI is installed; its stored authentication failed validation.
  Re-authentication must happen through `gh auth login`, never by pasting keys.

## Decisions

- Start with Python 3.12 only to constrain the tested dependency matrix.
- Lock resolved runtime/test dependencies. Keep fake Redis visibly distinct from
  a real server and exclude all fixture results from benchmark claims.
- First fault is a bad Redis hostname. API liveness is independent of Redis;
  readiness and successful writes/reads require Redis.
- Kubernetes uses Recreate for this first outage demonstration; revisit strategy
  when implementing the failed-rollout scenario. It must be scored separately.
- Lab CLI is a trusted operator tool, not the future restricted runtime gateway.
  It must never be given to the runtime LLM.
- Pilot checker: 5 HTTP requests/second, alternating PUT/GET, for 60 seconds;
  >=99% correct responses and p95 <=500 ms. Threshold is provisional and
  must be calibrated/frozen before any benchmark. Smoke checks use 2 seconds.

## Implemented

- Redis-backed FastAPI API, bounded request schema, 120-second disposable keys,
  request counters/histograms, sanitized dependency-error logs.
- Independent response checker rejects corrupted responses and superficial health.
- Explicit fixture fault/recovery demo.
- Named-cluster startup/reset/injection/recovery/cleanup CLI; first incident only.
  Selected-field snapshot and UID/resource-version preconditions; snapshot retained
  on failed recovery. This is scripted fault reversal, not harness rollback.
- Kubernetes manifests for API, Redis, Prometheus, and labeled request generator.
- Fast CI and manually gated kind smoke workflow (not run on GitHub).

## Checks and failures

- First fast test run: 31 passed; lint passed after formatting.
- Fixture demo: healthy 2/2, injected failure 0/2, recovery 2/2; live during
  fault, unready during fault, metrics present. Not a benchmark.
- Dependency consistency check passed. Nine Kubernetes YAML objects parsed.
- Starlette emits a deprecation warning for its current httpx TestClient adapter;
  compatibility passes, migration to its recommended adapter remains maintenance.
- Docker/WSL access failures prevent the live-cluster acceptance checks.
- Real HTTP + redis-py socket fixture test passed: healthy, unavailable endpoint,
  restored endpoint; all temporary API processes and sockets were closed.
  This used a fake Redis TCP server, not a real Redis daemon.
- Final checks on 2026-09-27: **33 tests passed** in 10.75 seconds; Ruff lint
  and format checks passed; `pip check` passed. One upstream TestClient
  deprecation warning remains as described above.
- Selected fixture JSON saved under `results/fixture-demo.json`; no private
  paths or credential patterns found in the project file scan.

## Budget and delivery

No API spending cap agreed; zero paid LLM calls and zero API spend.
GitHub owner/visibility and publication are not authorized yet.
No cloud infrastructure provisioned. License decision recorded in README.

## Next three actions

1. From a normal user terminal, confirm Docker Linux mode and WSL version;
   make Docker, kind, and kubectl available, then run `rackops doctor`.
2. Execute `rackops lab up`, `rackops lab inject`, `rackops lab recover`, and
   verify Prometheus data. Record actual output before accepting milestones 1–2.
3. Add the other two fault families and deterministic runbook baseline, then
   build the restricted gateway, evidence ledger, fake provider, and rollback tests.

## Remaining project scope

The structured harness, basic LLM agent, full runbook baseline, runtime RBAC,
evidence/action JSONL ledger, rollback, healthy/unsupported scoring, experiment
runner, heldout evaluation, dashboard, research verification, final portfolio
demo, GitHub publication, and CI execution are not complete. Do not infer any
of these from the first application tests or draft manifests.
