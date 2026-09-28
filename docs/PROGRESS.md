# RackOps progress

## Current milestone

2026-09-27: milestones 1–4 have partial local implementations. The API,
scenario runner, runbook, and gateway/adapter have offline tests. **No live
milestone is accepted yet:** real Redis, container build, Kubernetes readiness,
Prometheus scraping, runtime Role, and end-to-end repairs have not been run.

## Environment facts

- Dedicated repository created; branch `main` tracks the public
  https://github.com/MAndersonASU/rackops remote.
- Git 2.55.0 available. Python 3.12.14 from the desktop's bundled runtime used
  to create a project-local `.venv`; no system Python installation performed.
- Approximately 31.5 GiB total RAM, 4.2 GiB free, 685.7 GiB free disk at discovery.
- Docker Desktop and WSL processes are running. Docker exists in its per-user
  installation, outside PATH. Execution and directory reads return access denied,
  even after a folder-read permission grant. Linux container support is unverified.
- `kind` and `kubectl` not on PATH. WSL status/list return access denied.
- GitHub CLI authenticated as `MAndersonASU` through a device flow. Its token
  is in the ignored local `work/gh-config` folder because this sandbox could
  not write normal CLI settings. No token is in tracked files.

## Decisions

- Start with Python 3.12 only to constrain the tested dependency matrix.
- Lock resolved runtime/test dependencies. Keep fake Redis visibly distinct from
  a real server and exclude all fixture results from benchmark claims.
- First tested fixture fault is a bad Redis hostname. API liveness is independent of Redis;
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
- Named-cluster startup/reset/injection/recovery/cleanup CLI.
  Selected-field snapshot and UID/resource-version preconditions; snapshot retained
  on failed recovery. This is scripted fault reversal, not harness rollback.
- Kubernetes manifests for API, Redis, Prometheus, and labeled request generator.
- Trusted runner now supports bad Redis host, wrong Service target port,
  unavailable image, Redis shutdown, and healthy cases. All need live checks.
- Deterministic runbook rules and a typed gateway with evidence IDs, action
  limits, field restrictions, version checks, JSONL records, and rollback.
- In-cluster HTTP adapter and namespaced `rackops-agent` Role/RoleBinding;
  mock-transport tests pass, but real RBAC has not been exercised. Agent Pod,
  LLM strategies, and full experiment runner are still absent.
- A restricted runbook Job is wired to the operator CLI. After a proposed
  repair, its trusted checker waits for rollout readiness and probes real
  writes/reads for 60 seconds; this path is not yet run in a cluster.
- Basic and structured strategy loops have scripted fake-provider tests. The
  fake is labeled ineligible for benchmark claims and makes zero paid calls.
  Hosted-model transport and live comparison have not been implemented.
- Fast CI and manually gated kind smoke workflow (not run on GitHub).

## Checks and failures

- First fast test run: 31 passed; lint passed after formatting.
- Fixture demo: healthy 2/2, injected failure 0/2, recovery 2/2; live during
  fault, unready during fault, metrics present. Not a benchmark.
- Initial dependency consistency check passed. The first nine Kubernetes YAML
  objects parsed; later RBAC additions are covered by YAML/Role tests.
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
- Continuation checks: **62 tests passed**, Ruff lint/format and `pip check`
  passed. Tests cover three proposed repairs, healthy no-op, unsupported
  escalation, denied fields, stale state, failed repair/rollback, and mocked
  Kubernetes REST operations. All are offline; only the transport fixture uses
  real HTTP sockets, against simulated Redis.

## Budget and delivery

No API spending cap agreed; zero paid LLM calls and zero API spend.
The owner authorized automatic GitHub publication on 2026-09-27. Public
repository `MAndersonASU/rackops` exists, with description, MIT license, and
topics. Three local commits through `cbc07ef` were pushed to `main` and remote
tracking verified. The first Git transport attempt failed under Windows
Schannel; a CA bundle exported from the local Windows trust store allowed a
verified TLS Git push using the existing GitHub CLI login. TLS verification
stayed enabled. GitHub Actions `deterministic checks` completed successfully
for `cbc07ef` (run 36368068846). The manually gated kind smoke job has not run.
No cloud infrastructure provisioned. Source code is under MIT; no framework
code was copied.

## Next three actions

1. From a normal user terminal, confirm Docker Linux mode and WSL version;
   make Docker, kind, and kubectl available, then run `rackops doctor`.
2. Execute `rackops lab up`, `rackops lab inject`, `rackops lab recover`, and
   verify Prometheus data. Record actual output before accepting milestones 1–2.
3. Run the restricted baseline Job and verify Role permissions/denials in the
   live cluster. Then add hosted-model transport with a budget cap before any
   paid evaluation and implement the independent experiment runner.

## Remaining project scope

Hosted LLM transport for the structured/basic loops, full live runbook, runtime RBAC
integration, healthy/unsupported live scoring, experiment runner, heldout
evaluation, dashboard, and final portfolio demo are not complete. The evidence
ledger and rollback core have offline
tests only. Do not infer live success from fixtures or draft manifests.
