# RackOps progress

## Current milestone

2026-09-27 (2026-09-28 UTC): a manually triggered GitHub Actions kind run
(36370314133) passed all five development scenarios: three real repairs,
unsupported escalation with zero repairs, and healthy no-op with zero repairs.
This is one CI lab smoke, not a held-out benchmark or an LLM comparison.
Explicit Role allow/deny checks also passed in run 36371065150. The first live
serial evaluator run 36371654019 completed three valid setups but passed 2/3;
its original output omitted the failing case, so per-case diagnostics were
added. Run 36373009068 reproduced the 2/3 result and showed stale image history
caused the Redis-host misclassification. Diagnosis now uses current-Pod image
status and current dependency logs. Run 36374074466 passed all 3/3 diagnostic
cases and a live Prometheus rate query. Run 36374095023 completed five healthy
calibration windows; their 3.502 ms worst p95 selected the declared 50 ms floor,
which is frozen as `rackops-recovery-v1`. Laptop setup and hosted execution still
need checks.

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
- GitHub CLI authenticated as `MAndersonASU` through a device flow. The login
  is now in the standard GitHub CLI settings directory. A temporary duplicate
  project-local login was cleared with `gh auth logout`; its remaining file
  contains no token. No token is in tracked files.

## Decisions

- Start with Python 3.12 only to constrain the tested dependency matrix.
- Lock resolved runtime/test dependencies. Keep fake Redis visibly distinct from
  a real server and exclude all fixture results from benchmark claims.
- First tested fixture fault is a bad Redis hostname. API liveness is independent of Redis;
  readiness and successful writes/reads require Redis.
- Kubernetes uses Recreate so the broken-image scenario produced a user-facing
  outage in the first CI smoke. A different rollout strategy could keep old
  replicas serving and must be scored separately.
- Lab CLI is a trusted operator tool, not the restricted runtime gateway.
  It must never be given to the runtime LLM.
- Frozen checker `rackops-recovery-v1`: 5 HTTP requests/second, alternating
  PUT/GET, for 60 seconds; >=99% correct responses and p95 <=50 ms. It was
  frozen from run 36374095023 before holdout. Smoke checks use 2 seconds.

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
  unavailable image, Redis shutdown, and healthy cases. All five passed one
  real CI kind smoke; laptop execution remains unverified.
- Deterministic runbook rules and a typed gateway with evidence IDs, action
  limits, field restrictions, version checks, JSONL records, and rollback.
- In-cluster HTTP adapter and namespaced `rackops-agent` Role/RoleBinding;
  mock-transport tests pass. A real restricted Job handled all five scenarios
  in CI; explicit Role allow/deny checks passed in run 36371065150.
  Hosted LLM strategy execution is implemented but has not run live.
- A restricted runbook Job is wired to the operator CLI. After a proposed
  repair, its trusted checker waits for rollout readiness and probes real
  writes/reads for 60 seconds; all three repair paths passed in CI kind.
- Basic and structured strategy loops have scripted fake-provider tests. A
  bounded OpenAI Responses transport uses strict schema output, `store: false`,
  retries, validated usage, pre-call budget reservation, and owner-supplied
  model/prices/cap. The trusted runner injects an ephemeral Secret into a
  restricted Job. Transport and Job construction are offline-tested; zero paid
  calls have been made.
- Fast CI and manually gated kind smoke workflow; one full five-case smoke passed.
- Static results dashboard generator reads selected JSON and labels replay,
  fixture, live kind, and benchmark eligibility. Six selected records render;
  no held-out benchmark results are present.
- Trusted `evaluate-dev` runner resets between known scenarios, keeps hidden
  truth outside the runtime Job, scores its decision against a separate 60-second
  request-check Job, and stores JSONL under ignored `results/raw/`. It has
  offline boundary tests. Run 36371654019 executed three valid cases and passed
  2/3; case-level diagnostics were added for the rerun.
- `calibrate-dev` validates repeated complete healthy windows and writes an
  ignored raw record plus an explicitly unfrozen threshold candidate. Run
  36374095023 completed five windows; the fixed formula selected 50 ms and the
  reviewed result is now frozen separately as `rackops-recovery-v1`.
- The reduced holdout manifest is frozen at 10 configurations, 2 repetitions,
  and 3 strategies (60 scheduled attempts). Its deterministic schedule varies
  bounded fault values and API replicas, randomizes strategy order, and supports
  only hash-matched resume. No holdout attempt has run.

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
- On 2026-09-27 (2026-09-28 UTC), the first manual kind run (36368513075)
  started the cluster and manifested the Redis-host fault, but the runbook
  escalated because an unready deployment with no previous image was mistaken
  for an unknown image fault. A regression test and rule fix were pushed.
  Another run (36368754110) had an intermittent first smoke check of 2/4
  correct requests after startup; its cause is still unknown. Per-request
  failure reasons were added for future diagnosis. Neither run is a success.
- Manual kind run 36368976410 on commit `6027e26` passed: healthy setup 4/4,
  injected Redis-host fault 0/4, restricted runbook decision
  `verified_repair`, one repair in 10 gateway calls, 62.174 seconds elapsed
  including the full request window, recovery check 4/4. It used real Redis
  and a real Kubernetes cluster on a GitHub Actions runner, not this laptop.
  Fast CI also passed. Latest local suite: **64 tests passed** with Ruff
  lint/format checks; one upstream Starlette warning remains.
- Run 36369746983 on `363b6f7` passed all three repair families. Its
  unsupported-fault injection then timed out waiting for `Available=false`
  after Redis scaled to zero; zero desired replicas can still satisfy that
  Deployment condition. The runner now waits for zero ready replicas and the
  fault request check.
- Run 36370314133 on `42d9c9f` passed all five scenarios in a real kind
  cluster with Redis. Each repairable fault failed 0/4 smoke requests, was
  diagnosed with the expected cause, repaired once, passed the full 60-second
  request window, and recovered to 4/4. Redis outage escalated with zero
  repairs and healthy state took no action. Fast CI passed. Latest local
  suite: **67 tests passed**, Ruff lint/format passed, one upstream Starlette
  warning remains. Selected per-case summaries are in `results/`.
- Run 36371065150 on `575a636` again passed all five scenarios and explicit
  Kubernetes RBAC checks: API Deployment patch allowed; Redis Deployment patch,
  secret listing, and Pod patch denied. The independent development runner is
  being added after that run. Latest local suite: **72 tests passed**, Ruff
  lint/format and `pip check` passed; one upstream Starlette warning remains.
- Run 36371654019 on `ad0b033` passed all earlier five-case and RBAC stages.
  Its new serial evaluator completed three valid attempts but passed 2/3. The
  summary did not expose which case failed, so the runner now includes each
  case's decision, independent-check metrics, and score. Current local suite:
  **92 tests passed** with Ruff lint/format; no hosted API call was made.
- Run 36373009068 on `4ab492d` again passed the standalone cases and RBAC,
  then reproduced 2/3 in the serial evaluator. The bad Redis-host case was
  misclassified from stale image history; its wrong repair failed independent
  verification and rolled back. Healthy and unsupported cases passed. A
  current-Pod/current-log regression fix now passes locally.
- Run 36374074466 on `c9c9a51` passed the five standalone scenarios, explicit
  RBAC checks, live Prometheus rate query, and all 3/3 diagnostic evaluator
  cases. Run 36374095023 completed five healthy calibration windows at 300/300
  correct requests. Current local suite: **94 tests passed**.
- Run 36460413617 on `0b934e8` revalidated the five scenarios, RBAC checks,
  live metrics, and all 3/3 evaluator cases against frozen
  `rackops-recovery-v1`. The two successful 300-request windows had p95 3.142
  and 3.061 ms under the 50 ms limit. Current local suite: **104 tests passed**.
- Run 36461878925 on `3609f08` passed the same live checks plus a separate
  two-replica development variation with a non-holdout Redis-host value. Its
  repair passed before the serial evaluator again completed 3/3.

## Budget and delivery

No API spending cap agreed; zero paid LLM calls and zero API spend.
The owner authorized automatic GitHub publication on 2026-09-27. Public
repository `MAndersonASU/rackops` exists, with description, MIT license, and
topics. `main` tracks the GitHub remote. The first Git transport attempt failed under Windows
Schannel; a CA bundle exported from the local Windows trust store allowed a
verified TLS Git push using the existing GitHub CLI login. TLS verification
stayed enabled. GitHub Actions fast checks, the full manual five-case kind
smoke, and the explicit Role checks passed in run 36371065150.
No paid cloud infrastructure provisioned; GitHub Actions uses ephemeral hosted
runners. Source code is under MIT; no framework
code was copied.

## Next three actions

1. Revalidate all live scenarios against frozen `rackops-recovery-v1`.
2. After an explicit API cap and model configuration, execute the frozen reduced
   holdout without tuning on its outcomes.
3. From a normal user terminal, confirm Docker Linux mode and WSL version;
   make Docker, kind, and kubectl available, then run `rackops doctor` locally.

## Remaining project scope

Live hosted execution, held-out
evaluation, dashboard refinement, and local laptop reproduction are incomplete.
Rollback failure paths still need live checks. The evidence ledger and rollback
core have offline tests. Do not infer benchmark or LLM success from smoke checks.
