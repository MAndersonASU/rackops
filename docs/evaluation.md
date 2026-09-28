# Evaluation protocol (held-out comparison not yet executed)

A five-case development smoke passed in GitHub Actions kind on 2026-09-28 UTC.
It is not the holdout below. A trusted serial runner now implements separate
setup, agent, independent request check, and reset records for the runbook,
and two three-case live CI checks passed 2/3 attempts. Run 36373009068 identified
the failure: stale image revision history caused the runbook to misclassify a
current Redis-host fault. Independent verification rejected the wrong repair and
rollback succeeded. Diagnosis now uses current-Pod image status and current
dependency logs, pending a live rerun. The LLM strategies have scripted tests
and an offline-tested hosted transport. No hosted call or model comparison has occurred.

Each attempt will start from a checked healthy baseline. The trusted test
runner injects one fault and confirms it manifested before starting a strategy.
It then lets that strategy observe, optionally repair, and stop or escalate.
The independent checker measures real writes and reads, readiness, and rollout
state. Finally, the runner resets the lab and checks readiness again.

The deterministic runbook, a basic tool-calling LLM agent, and a structured
harness will share the same restricted operations. The structured harness adds
explicit evidence references, state transitions, bounded retries, and verified
rollback. This bundled comparison will not isolate each feature's causal effect.

Pilot limits are at most 15 agent calls, 2 repair attempts, and 5 minutes per
incident. The provisional recovery check is 5 HTTP requests per second for
60 seconds, >=99% correct responses, and p95 latency <=500 ms. That threshold
must be calibrated from healthy runs, given a sensible floor, and frozen before
any held-out evaluation. `calibrate-dev` now validates 3–10 complete healthy
windows and produces an unfrozen candidate: twice the worst healthy p95 with a
50 ms floor. Five runs are the documented default. Time to recovery will include
the final 60-second observation window.

Target holdout: 12 repairable configurations (4 per family), 4 healthy, and
4 unsupported. Three serial repetitions per strategy would be 180 attempts.
If API budget or time is lower, the declared fallback is 10 configurations,
2 repetitions, 3 strategies, and 60 attempts. Repetitions are not independent
new incidents. Invalid setups are counted separately, never as agent successes.

No pilot, holdout, model call, or paid experiment has happened yet. No model or
budget has been selected. Hosted runs require an explicit key, model, current
input/output prices, and command-wide cap; an unknown-usage failure stops later
calls. All published fixture output is marked ineligible for benchmark claims.
