# Results: development checks only

No real Kubernetes benchmark or LLM evaluation has been run.

Development verification on 2026-09-27: **62 pytest tests passed** in 11.38
seconds on Windows/Python 3.12.14. Ruff lint and format checks and `pip check`
passed. One upstream Starlette TestClient deprecation warning remains.
The transport test used real HTTP/Redis-protocol sockets with simulated Redis.
GitHub Actions fast checks also passed for commit `cbc07ef` (run 36368068846);
the manual kind smoke job has not run.

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
