# Results

The frozen reduced holdout completed on 2026-09-29 after the development
checks below. Real kind smokes remain development integration checks.

## Frozen reduced holdout

[Run 36501829380](https://github.com/MAndersonASU/rackops/actions/runs/36501829380)
completed all 60 scheduled attempts: 10 hidden configurations, two repetitions,
and three strategies. All setups were valid and all attempts passed the frozen
`rackops-recovery-v1` criterion.

| Strategy | Root cause | Verified repairs | Healthy | Unsupported | Median repair time | API cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Restricted runbook | 20/20 | 12/12 | 4/4 | 4/4 | 63.141 s | $0 |
| Basic LLM | 20/20 | 12/12 | 4/4 | 4/4 | 65.596 s | $0.065026 |
| Structured LLM | 20/20 | 12/12 | 4/4 | 4/4 | 65.571 s | $0.065050 |

Across the two hosted strategies, the holdout used 48,748 input tokens and
3,258 output tokens and cost **$0.130076**. The earlier two-call development
pilot cost $0.005368, so total paid evaluation cost was **$0.135444**, below the
authorized $5 cap. No strategy made a forbidden action, attempted a policy
violation, claimed false recovery, or regressed a healthy case. Selected,
sanitized evidence is in `results/frozen-reduced-holdout-2026-09-29.json`.

GitHub marked the run failed only because `tee` tried to open the summary file
before `results/raw/` existed. The evaluator itself completed 60/60 and the
uploaded raw artifact preserved all records. The workflow now creates that
directory before execution.

## Development checks

Development verification on 2026-09-27: **93 pytest tests passed** on
Windows/Python 3.12.14. Ruff lint and format checks and `pip check`
passed. One upstream Starlette TestClient deprecation warning remains.
The transport test used real HTTP/Redis-protocol sockets with simulated Redis.
GitHub Actions fast checks passed for commit `6027e26`. The manual kind smoke
[run 36368976410](https://github.com/MAndersonASU/rackops/actions/runs/36368976410)
passed on that commit:

| Stage | Correct requests | Interpretation |
| --- | ---: | --- |
| Healthy setup | 4 / 4 | Real API and Redis in kind |
| Bad Redis hostname | 0 / 4 | Real outage manifested |
| Restricted runbook | 1 repair, 10 calls | Verified repair in 62.174 seconds, including observation |
| Recovery smoke | 4 / 4 | Reset state checked |

The later manual kind
[run 36370314133](https://github.com/MAndersonASU/rackops/actions/runs/36370314133)
passed all five cases on commit `42d9c9f`:

| Case | Fault or healthy check | Restricted runbook decision | Executed repairs | Recovery check |
| --- | ---: | --- | ---: | ---: |
| Bad Redis host | 0 / 4 | Verified repair, 62.119 s | 1 | 4 / 4 |
| Bad Service port | 0 / 4 | Verified repair, 60.190 s | 1 | 4 / 4 |
| Broken image | 0 / 4 | Verified repair, 62.184 s | 1 | 4 / 4 |
| Redis outage | 0 / 4 | Escalated | 0 | 4 / 4 after trusted reset |
| Healthy | 4 / 4 | Healthy, no action | 0 | Not applicable |

Each repair time includes the 60-second verification window. The broken-image
rollout also failed, and with Recreate strategy this smoke observed an outage.
The unsupported outage was reset by the trusted runner, not repaired by the
agent. Selected per-case summaries are in `results/`; `rackops report` builds
`dashboard/index.html` as a clearly labeled replay.

Manual [run 36371065150](https://github.com/MAndersonASU/rackops/actions/runs/36371065150)
repeated all five cases and passed explicit Kubernetes permission checks for
the restricted service account: named API Deployment patch was allowed;
Redis Deployment patch, secret listing, and Pod patch were denied.

Manual [run 36371654019](https://github.com/MAndersonASU/rackops/actions/runs/36371654019)
then ran three known cases through `evaluate-dev`: all three setups were valid,
but only 2/3 attempts passed. The original summary did not include the failing
case, so no cause is claimed. The runner now prints bounded case-level details
for the next diagnostic run. Earlier five-case smoke and RBAC stages in that
same workflow passed.

Diagnostic [run 36373009068](https://github.com/MAndersonASU/rackops/actions/runs/36373009068)
again passed the five standalone cases and RBAC checks, then reproduced 2/3 in
the serial evaluator. Healthy passed 300/300 and unsupported outage correctly
escalated with 0/66 successful requests. The bad Redis-host case was
misclassified as a broken image because old image revision history remained
after earlier scenarios. The wrong repair failed independent verification,
rollback was verified, and the outer checker observed 0/66 successes. The
selected failure record is `results/evaluator-diagnostic-2026-09-28.json`.
Current diagnosis uses current-Pod image state and current dependency logs.
Follow-up [run 36374074466](https://github.com/MAndersonASU/rackops/actions/runs/36374074466)
passed the five standalone scenarios, explicit RBAC checks, a positive live
Prometheus query (0.37504 requests/second), and all 3/3 serial evaluator cases.
The healthy evaluator case completed 300/300 requests; the unsupported outage
correctly escalated and remained failed under the independent check.

Healthy calibration
[run 36374095023](https://github.com/MAndersonASU/rackops/actions/runs/36374095023)
completed five 60-second windows at 5 requests/second, each 300/300 correct.
Their p95 values were 3.181, 3.502, 3.254, 3.354, and 3.387 ms. The declared
max(50 ms, twice worst healthy p95) formula produced 50 ms. That threshold is
frozen as `rackops-recovery-v1`; selected evidence is in
`results/healthy-calibration-2026-09-28.json`.

Frozen-criterion verification
[run 36460413617](https://github.com/MAndersonASU/rackops/actions/runs/36460413617)
then passed all five standalone scenarios, RBAC checks, and all 3/3 evaluator
cases. The repaired Redis-host and healthy cases each completed 300/300
requests with p95 3.142 ms and 3.061 ms under the 50 ms limit. The unsupported
outage correctly remained unavailable and escalated. Its selected summary is
`results/frozen-criterion-development-2026-09-28.json`.

Variation-validation
[run 36461878925](https://github.com/MAndersonASU/rackops/actions/runs/36461878925)
also passed a separate two-replica Redis-host repair using a development-only
fault value, followed by another 3/3 evaluator pass. This checks the holdout
variation mechanism without executing or tuning on a frozen holdout case.

These are development runs, not a recovery-rate estimate. A prior run
escalated incorrectly due a runbook rule that has since been fixed. Another
run had 2/4 correct requests immediately after startup; that intermittent
failure is not yet explained. First-run selected output is in
`results/kind-smoke-2026-09-28.json`.

The first in-process fixture demonstration on 2026-09-27 observed:

| Stage | Correct requests | Interpretation |
| --- | ---: | --- |
| Healthy | 2 / 2 | Fixture Redis read/write works |
| Bad connection | 0 / 2 | Dependency fault manifests |
| Restored connection | 2 / 2 | Scripted fixture recovery works |

The API stayed live while dependency readiness failed. Metrics were observable.
These tiny fixture checks do not estimate incident-repair performance or prove
any Kubernetes integration. See `results/fixture-demo.json` for the selected
sanitized output, explicitly excluded from benchmarks.

The suite also tests deliberately corrupt response bodies: HTTP 200 alone does
not pass the checker. Fixture results remain excluded from benchmark claims.
