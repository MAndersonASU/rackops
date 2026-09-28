# Three-minute prepared-cluster demo

This walkthrough was exercised in the manual GitHub Actions kind run
[36370314133](https://github.com/MAndersonASU/rackops/actions/runs/36370314133).
It has not been rerun on the owner's Windows laptop. Use disposable data only.

Before recording, follow the [setup instructions](../README.md) in a normal
terminal. Confirm `rackops doctor` reports Docker in Linux mode, kind, and
kubectl ready. Run `rackops lab up` before starting the timer. The cluster is a
local test environment; a **Pod** is a running container, while a **Service**
provides a stable address to it. Keep the terminal visible for the JSON output.

1. **0:00–1:20, repair.** Say: “The trusted runner changes the API's Redis host;
   the runtime agent cannot call that runner.” Execute:

   ```text
   rackops lab inject --scenario bad_redis_host
   rackops lab baseline --expect verified_repair --expect-cause bad_dependency_configuration --expect-repairs 1
   rackops lab recover
   ```

   Point out `fault_confirmed`, zero correct requests during the fault, the
   evidence-backed runbook decision, and one repair. The roughly 60-second
   baseline step includes independent write/read verification; do not skip it
   to shorten the recording.

2. **1:20–1:50, healthy no-op.** Say: “A healthy system must not trigger a
   repair.” Execute:

   ```text
   rackops lab inject --scenario healthy
   rackops lab baseline --expect healthy_no_action --expect-cause healthy --expect-repairs 0
   ```

   Show the passing request check and zero executed repairs.

3. **1:50–2:40, unsupported outage.** Say: “Only the trusted runner can stop
   Redis. The restricted agent can observe the outage, but cannot scale Redis
   back up.” Execute:

   ```text
   rackops lab inject --scenario redis_outage
   rackops lab baseline --expect escalated --expect-cause unsupported_dependency_outage --expect-repairs 0
   rackops lab recover
   ```

   Show the escalation, zero repairs, and the trusted reset returning requests
   to 4/4. End with the static `dashboard/index.html` replay and explain that
   this development smoke does not establish an LLM comparison or benchmark.

After recording, run `rackops lab down` to remove the disposable cluster. If a
step fails, retain its actual output and do not describe the incident as
repaired. Use `rackops lab recover` when an injection snapshot exists; the
snapshot remains if recovery checks fail.
