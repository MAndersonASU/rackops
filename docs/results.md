# Results: development checks only

No Kubernetes benchmark or LLM evaluation has been run. One real kind smoke
passed on a GitHub Actions runner; it is a development integration check.

Development verification on 2026-09-27: **64 pytest tests passed** on
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

This is one development run, not a recovery-rate estimate. A prior run
escalated incorrectly due a runbook rule that has since been fixed. Another
run had 2/4 correct requests immediately after startup; that intermittent
failure is not yet explained. Selected output is in
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
not pass the checker. No tokens, API cost, root-cause accuracy, or held-out
recovery rates are reported because those experiments do not yet exist.
