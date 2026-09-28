# Evaluation protocol (held-out comparison not yet executed)

A five-case development smoke passed in GitHub Actions kind on 2026-09-28 UTC.
It is not the holdout below. A trusted serial runner now implements separate
setup, agent, independent request check, and reset records for the runbook,
but that runner itself still needs a live CI check. The LLM strategies have
only scripted fake-provider tests. No model comparison has occurred.

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
any held-out evaluation. Time to recovery will include this observation window.

Target holdout: 12 repairable configurations (4 per family), 4 healthy, and
4 unsupported. Three serial repetitions per strategy would be 180 attempts.
If API budget or time is lower, the declared fallback is 10 configurations,
2 repetitions, 3 strategies, and 60 attempts. Repetitions are not independent
new incidents. Invalid setups are counted separately, never as agent successes.

No pilot, holdout, model call, or paid experiment has happened yet. No model or
budget has been selected. All published fixture output is marked ineligible for
benchmark claims.
