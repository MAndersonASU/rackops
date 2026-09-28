# Results: development checks only

No Kubernetes benchmark or LLM evaluation has been run. Real kind smokes
passed on GitHub Actions runners; they are development integration checks.

Development verification on 2026-09-27: **67 pytest tests passed** on
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
not pass the checker. No tokens, API cost, held-out root-cause accuracy, or
recovery rates are reported because those experiments do not yet exist.
