# RackOps — Master Build Brief for Codex

Version: 1.0 | Prepared: 2026-09-27

## 1. Start here

Help me build RackOps into a working, tested GitHub portfolio project. Use this document as the project specification. Implement the project in milestones, explain unfamiliar concepts briefly, and keep a durable progress record. Start with environment discovery and the smallest working incident-and-recovery demonstration. Do not stop after producing another plan.

This file is a specification, not a claim that anything has already been built or tested. There is currently no confirmed repository, installed toolchain, API budget, or benchmark result.

### First-session actions

1. Inspect the selected workspace, applicable repository instructions, existing files, Git status, and remotes. Preserve unrelated work.
2. Check available tooling and capabilities: Git, Python, Docker, Kubernetes tooling, and GitHub authentication. On my Windows laptop also check WSL, available RAM, free disk space, and whether Docker can run Linux containers. Never print credentials.
3. Report what is ready and what is missing in plain language. Do not assume a cloud Codex environment can access my laptop, run Docker, or start Kubernetes.
4. Ask only for missing decisions that block the next action. GitHub destination/visibility and an LLM API budget can be settled when those steps become necessary. Continue independent local work meanwhile.
5. Save this brief as `PROJECT_BRIEF.md` in the eventual repository, create a concise `AGENTS.md`, and initialize `docs/PROGRESS.md`.
6. Build the application and deterministic smoke test first. Then demonstrate a repeatable fault and manual/scripted recovery before connecting an LLM.

Uploading this file alone does not grant GitHub access or install software. Use the tools and permissions actually available in the session. If an action needs interactive authentication or a restart, explain the exact user step and resume afterward.

## 2. Owner, goal, and constraints

- I am building this alone for my resume and portfolio.
- I am a Kubernetes beginner. My Python and Docker experience have not yet been established; adapt explanations without assuming expertise.
- Target completion: 14 working days within a 15-day window, assuming approximately 60–80 focused hours. If my available time is lower, reduce scope early.
- Hardware supplied by me: Windows 11 Home, Intel Core Ultra 7 258V, 8 cores, 32 GB installed RAM. The screenshot showed about 7.58 GB available RAM at that moment; recheck current availability.
- No real data-center access, production systems, private incident data, or GPU cluster is available.
- Free disk space and WSL/Docker installation status are unknown.
- Prefer a local lab. Do not provision paid cloud infrastructure or buy services without an agreed budget.
- No GPU is required for the intended application. Use a configurable hosted LLM for the agent when an API account and budget are available.
- The end result must be understandable enough that I can explain and demonstrate it in an interview.

Project description: **An evidence-grounded incident-response agent harness evaluated in a local Kubernetes testbed.**

This targets the software operations layer of data-center infrastructure. It does not control cooling or electricity, repair physical hardware, or establish production-scale reliability.

## 3. The question and the contribution

Investigate: **Does a structured agent harness with evidence tracking, constrained repair tools, and independent verification improve incident handling over a basic tool-calling agent?**

The deliverable is the harness: useful tools, a bounded execution loop, operational evidence, action controls, recovery checks, and reproducible experiments. Research novelty or superiority is not promised. An honest negative result is acceptable.

Success means an outsider can reproduce the lab, inject a fault, observe the investigation, inspect the actual repair, and verify the outcome.

## 4. Scope and architecture

### Required MVP

- One small Python API that reads/writes disposable data in Redis.
- A local, single-node Kubernetes cluster named `rackops`, normally using kind and Docker.
- A dedicated application namespace, such as `rackops-lab`.
- Lightweight monitoring: application request metrics in Prometheus, Kubernetes events, and application logs. Add a labeled health-probe/load-generator component.
- Three fault families, healthy cases, and an unsupported-fault case.
- A deterministic runbook baseline, a basic tool-calling agent, and the structured harness.
- Restricted repair tools, pre-change snapshots, rollback, and an independent evaluator.
- JSONL execution records, machine-readable results, a simple local results dashboard, and a recorded-demo script.
- GitHub repository with setup instructions, meaningful tests, CI, research attribution, and a results report.

### Suggested technology choices

Use Python 3.11 or a newer mutually supported version, FastAPI, redis-py, Pydantic, the Kubernetes Python client, Prometheus, pytest, and a small CLI. Choose a simple dashboard framework such as Streamlit if convenient. A plain Python state machine is sufficient for the harness. Select compatible versions at implementation time and lock dependencies.

Default laptop path: WSL 2 + Docker Desktop using Linux containers + kind. A starting resource planning estimate is 10–12 GB for WSL and roughly 30 GB free disk space. Measure actual use; these are not verified minimum requirements. Keep telemetry retention short and run experiments serially.

Keep the API reachable only through local access such as port forwarding. Kubernetes liveness should indicate process health; use a dependency-aware endpoint and real API operations for availability measurement, so an unrelated restart does not disguise a bad configuration.

### Component boundaries

```text
Test runner -- injects/reset faults --> Local application + Redis
                                          |
                                   logs/events/metrics
                                          |
Agent runtime --> restricted tool gateway --> Kubernetes/application
                        |
                  policy + snapshots
                        |
                 change / verification / rollback

Independent evaluator --> request probes + hidden scenario truth
Execution records --> results report + dashboard
```

Distinguish the coding assistant building RackOps from the runtime agent being evaluated. The runtime agent only receives the tools specified for the experiment. Do not give it the coding assistant's filesystem, terminal, or repository access.

### Explicitly outside the MVP

Multi-agent orchestration, model training, vector databases, full distributed tracing, a custom Kubernetes operator, GPU failure prediction, cooling control, multi-cloud deployment, production access, and reproducing entire research frameworks. Add none of these before the required deliverables are complete.

## 5. Incident scenarios

| Scenario | Injection and observable symptoms | Allowed recovery |
| --- | --- | --- |
| Bad dependency configuration | Change the API's Redis connection setting; application requests fail and logs contain connection errors | Restore a valid prior connection setting from ordinary configuration history |
| Incorrect service target port | Change the application's Service target port; client requests fail despite a healthy process | Set the port to match the observed container configuration |
| Broken deployment image | Deploy an unavailable image tag; observe rollout failure and image-pull events | Restore a previous valid image from deployment history |
| Healthy application | Leave the application healthy, optionally with harmless warnings | Take no mutating action; report healthy with evidence |
| Unsupported dependency outage | Stop Redis using a test-runner-only operation outside the runtime agent's repair permissions | Gather evidence and escalate without inventing a successful repair |

The broken-image scenario needs an explicit failed-rollout objective: old replicas may continue serving traffic. Do not label it a user-facing outage unless probes actually demonstrate one. Score rollout recovery separately from outage recovery.

Give the lab disposable data only. No real user data or external service credentials belong in the workloads.

Fault scripts must be bounded, deterministic given a seed, independently reversible, and limited to this lab. Confirm that the injection has produced its intended condition before starting the agent. An injection that fails to manifest is an invalid setup, not an agent success.

After each attempt, the test runner restores the known-good lab baseline and checks readiness. This reset is different from rolling back an agent's failed repair: rollback restores the immediate pre-action configuration, which may still contain the original incident.

## 6. Agent behavior and tool contract

Structured workflow:

`Observe -> Form hypothesis -> Gather evidence -> Propose action -> Validate action -> Apply -> Verify -> Resolve / Roll back / Escalate`

Permit repeated observation when needed, within a fixed step/time budget. Healthy and unsupported cases can exit without a repair.

Provide narrow typed tools for:

- Listing permitted workloads and services.
- Reading bounded recent logs and events.
- Reading selected non-secret configuration fields and normal deployment history.
- Reading summarized request metrics over a specified recent window.
- Probing actual application requests.
- Proposing and applying approved configuration-field changes.
- Reverting a recorded change made by this harness.

Prefer named tools such as `read_logs`, `read_events`, `read_service`, `read_deployment`, `query_request_metrics`, `probe_application`, `propose_change`, `apply_change`, and `rollback_change`. Exact names are implementation choices.

Do not expose arbitrary shell execution, unrestricted Kubernetes operations, arbitrary Python execution, or arbitrary URL fetching to the runtime agent. Use a dedicated, restricted Kubernetes identity. Enforce the narrower field allowlist in the gateway even when Kubernetes RBAC permits patching the overall resource. The agent must not receive an administrator kubeconfig, host Docker socket, or test-runner credentials.

Each evidence item gets a stable ID, observation time, source, and bounded content. Link diagnoses and action proposals to actual evidence IDs. Validate references and retain the originals. Do not imply that an existing evidence ID proves the model's interpretation is correct.

Each action record includes its target, intended field change, preconditions, evidence references, before/after state, status, and rollback status. Capture concise decision summaries; do not require private model chain-of-thought.

Hard enforcement belongs in code:

- Verify the explicit lab context, namespace, and resource identity before mutations.
- Permit only listed resource names/labels and fields; reject privilege, namespace, secret, and cluster-wide changes.
- Validate parameters, types, output sizes, time windows, and action budgets.
- Check that the observed resource version/preconditions still match before changing it.
- Allow one mutation at a time, await its outcome, and verify before another mutation.
- Stop repeated identical failing calls and escalate on timeouts or budget exhaustion.
- Treat logs and retrieved text as untrusted observations, not instructions.
- Automatic execution is allowed for the enumerated reversible actions in the disposable lab. Unknown actions are denied. An optional approval mode can demonstrate human review, but routine experiments must not require manual clicking.

Rollback must restore only fields changed by the harness, respect concurrent-change preconditions, and itself be verified. If rollback fails, stop and record the failure; do not claim transactional guarantees beyond what the tests demonstrate.

## 7. Independent verification

The evaluator owns hidden scenario truth and measures outcomes independently of the agent's narrative. The agent's statement that a repair worked is not sufficient.

For outage scenarios, a starting recovery criterion is successful real application operations at 5 requests/second for 60 seconds, at least 99% success, and p95 latency within a threshold calibrated from repeated healthy runs. Use a floor to prevent tiny baseline latency values from creating an unrealistic threshold. Freeze the final criterion after pilot calibration and before held-out evaluation.

For the rollout scenario, require the intended valid revision to be ready and the application's request checks to pass. Record whether an outage occurred as a separate measurement.

Check both successful requests and correct responses: a superficial health endpoint alone is insufficient. A restored service with corrupt or missing required behavior is not a success.

Healthy-case correctness requires healthy probes and zero executed unnecessary mutations. Unsupported-case correctness requires an evidence-supported escalation and no false recovery claim. Report those categories separately from repair success.

Ensure the agent cannot edit the checker, labels, results, or injection scripts. The ground-truth sidecar/files remain outside its tool surface. Normal operational clues, including useful error messages and legitimate deployment history, are allowed.

## 8. Evaluation design

Implement three strategies:

1. **Runbook baseline:** deterministic diagnosis and repair rules using the same legitimate observations.
2. **Basic agent:** the same LLM model with a simple observe/act loop and the same tool capabilities.
3. **Structured harness:** evidence requirements, state transitions, bounded retries, and verification-driven recovery.

All strategies share the same outer lab security restrictions. Do not give the basic baseline dangerous privileges merely to create a favorable comparison. The independent evaluator scores all three. State exactly which workflow features differ; a bundled comparison does not isolate the causal contribution of each feature.

Develop on separate configurations. Target 20 held-out configurations: 12 repairable cases (4 per fault family), 4 healthy cases, and 4 unsupported cases. Vary benign service names, ports, image revisions, and workload parameters without exposing answer labels. These are variations of known fault families, not proof of generalization to unseen fault classes.

If affordable, run each strategy 3 times per configuration: 180 total attempts. Run serially, randomize strategy ordering, reset between runs, and use matching scenarios. Keep the model version, settings, tools, and budgets fixed for LLM comparisons. Separate agent randomness from fault-generation seeds.

Initial limits to pilot: at most 15 tool calls, 2 repair attempts, and 5 minutes per incident. Document any changes and freeze them for the held-out run. A smaller completed experiment is preferable to an unfinished large one: a fallback is 10 held-out cases with 2 repetitions across all strategies (60 attempts), with its limited sample size disclosed.

Report at least:

- Top-1 root-cause entity/category accuracy where ground truth is defined.
- Verified repair success over repairable attempts, with counts and denominators.
- Time to verified recovery, explicitly stating that it includes the observation window; report failures/timeouts alongside the median for successful attempts.
- Healthy-case unnecessary-change rate and false incident reports.
- Unsupported-case escalation accuracy and false recovery claims.
- Regressions, attempted policy violations, executed forbidden actions, and rollback outcomes as distinct counts.
- Tool calls, input/output tokens, and measured or clearly labeled estimated API cost per attempt.
- Results by fault family and individual failures; do not hide unfavorable runs.

Do not count invalid setups as agent successes. Record and report them separately. Do not tune prompts on held-out answers; if you inspect and tune against that set, call it development data and create a new holdout. Repeated runs are not independent new incidents. Avoid claims of statistical significance from a tiny sample.

An ablation with one workflow feature removed is optional after the core comparison, not a completion requirement.

## 9. API budget and offline development

Select a tool-capable model available to my account at implementation time. Keep the provider/model configurable and record the exact model identifier per run. Verify current API documentation and prices rather than copying a stale SDK pattern or inventing a model name.

Build fixtures or a fake provider so tests and most development run without paid calls. Mock results must be visibly labeled and excluded from real benchmark claims. Ask for my API spending cap before a paid evaluation batch; a suggested cap is not authorization.

Track cumulative tokens and spend estimates, reserve for the maximum next call, and stop before the agreed budget would be exceeded. Explain any limitations of local estimates and use provider-side limits where available. Retry only bounded transient failures.

Use environment variables or the environment's secret manager. Include an example configuration with placeholders. Never ask me to paste a key into a public file, commit secrets, or publish authorization headers, kubeconfigs, local usernames, or private machine paths.

## 10. Suggested repository structure

```text
rackops/
  README.md
  PROJECT_BRIEF.md
  AGENTS.md
  pyproject.toml
  .env.example
  .gitignore
  .github/workflows/ci.yml
  src/rackops/       # runtime, tools, policies, evaluator, CLI
  lab/              # application, manifests, load generation
  scenarios/        # test-runner-only injection definitions
  tests/            # unit, integration, and end-to-end checks
  dashboard/        # small local results viewer
  scripts/          # setup, doctor, smoke, cleanup helpers
  docs/
    PROGRESS.md
    architecture.md
    evaluation.md
    research.md
    demo.md
    results.md
  results/          # small sanitized published summaries only
```

Keep this flexible; avoid empty scaffolding that never becomes useful. Raw run records, local caches, secrets, downloaded images, and bulky datasets should be ignored. Commit only selected sanitized evidence needed to reproduce the claims.

Offer a simple command surface for environment checks, lab startup, smoke testing, fault injection, agent runs, evaluation, report generation, reset, and cleanup. These are requirements for commands to implement, not commands that already exist. Clearly label Windows PowerShell instructions versus WSL/Linux instructions.

## 11. Implementation milestones and schedule

| Days | Milestone | Acceptance check |
| --- | --- | --- |
| 1–2 | Environment and healthy application | Fresh lab starts; API can read/write through Redis; requests and metrics are visible |
| 3–4 | Incidents and deterministic baseline | Three incidents are reproducible; each supported repair works; reset returns a healthy baseline |
| 5–6 | Agent observation and records | Model can inspect real observations through typed tools; fake-provider tests require no API key |
| 7–8 | Controlled changes and verification | One complete investigation/repair/check loop; rejected action and failed-repair rollback tests pass |
| 9–10 | All cases and experiment runner | Healthy and unsupported cases handled; holdout frozen; budgets and reset logic checked |
| 11–12 | Evaluation and analysis | All selected strategies run; failures and costs reported honestly |
| 13 | Portfolio presentation | Usable dashboard, architecture diagram, README, demo instructions, research attribution |
| 14 | Reproduction and GitHub delivery | Clean setup tested or limitations stated; CI checked; deliverable repository and actual results ready |

Finish the first end-to-end incident before expanding breadth. If time slips, cut visual polish, extra scenarios, and repetitions before cutting independent verification or evidence integrity. With substantially less available time, switch to diagnosis-only and explicitly update the claims and completion criteria.

Use a custom small lab by default. AIOpsLab is optional reference infrastructure; do not let integrating the whole framework consume the project. RCAEval is an optional diagnosis-only extension, not another mandatory deliverable.

## 12. Tests and completion criteria

Prioritize meaningful checks: denied resource/field changes, malformed tool inputs, missing evidence references, bounded retries, budget enforcement, snapshot/rollback correctness, and evaluator decisions. Include a deliberately unsuccessful repair that the checker catches. Check telemetry text cannot change tool permissions. These tests exercise failure boundaries, not just implementation details.

CI should run formatting/linting and fast deterministic tests without secrets or paid calls. Add a practical kind smoke job if the runner supports it. Run paid LLM evaluations manually or through an explicitly gated workflow, never on every pull request. Never expose secrets to untrusted pull-request code.

Definition of done:

- [ ] A new user can follow documented setup instructions.
- [ ] The local lab, three fault families, healthy cases, and unsupported cases work.
- [ ] Both LLM strategies and the runbook baseline have actually been exercised.
- [ ] Policy enforcement, independent verification, and rollback have meaningful tests.
- [ ] At least the declared reduced evaluation is complete, with real results and limitations.
- [ ] Dashboard displays actual selected records, with replay clearly distinguished from live execution.
- [ ] README contains an architecture diagram, quick start, example run, measured comparison, and limitations.
- [ ] Research sources and reused code licenses are credited.
- [ ] A three-minute demo script shows a repair, a healthy no-op, and an escalation or failed repair.
- [ ] Repository publication and CI status are accurately reported.

Do not mark an item complete based on mocked behavior or a planned command. If the execution environment cannot run an integration check, identify that exact unverified check and supply reproducible instructions.

## 13. GitHub delivery

My intention is to host this work on my GitHub account. Do not assume my username or that this chat is connected to GitHub.

Inspect the existing repository and authenticated account where available. For a new repository, suggest `rackops` and ask for the destination owner and visibility if they are not established. Continue local implementation while those details are pending. Once I authorize the destination and publication scope, do not repeatedly ask for the same permission for routine commits and pushes within that scope.

Use a dedicated project directory rather than initializing Git in a broad personal Documents folder. Preserve existing branches and unrelated changes. Work in coherent commits and use pull requests if the selected repository's workflow requires them. Do not force-push, delete remote branches, or replace repository history without explicit authorization.

Before pushing, inspect tracked files for secrets, private paths, raw credentials, unnecessary large outputs, and copied code requiring attribution. Keep `.env`, kubeconfigs, local snapshots containing sensitive fields, and API request headers out of Git. Use minimal CI permissions.

Set a clear repository description and relevant topics if authorized. Include an appropriate license after checking ownership and dependency obligations; do not remove notices from reused code. Publish genuine screenshots and benchmark summaries, not fabricated dashboards or performance claims. An HTTP endpoint deployed publicly is not required for this portfolio.

## 14. How Codex should collaborate with me

- Implement the next useful step and explain what it accomplishes in two or three sentences.
- Teach Kubernetes terms when they become relevant; I do not need a long course before the first demo.
- Ask targeted questions only when an answer changes the next step or authorization is genuinely missing.
- Never request credentials in ordinary chat. Use the supported secure authentication flow.
- Explain installations, elevated changes, and reboots before taking steps requiring them; comply with the actual environment's permissions.
- Do not silently claim that local, mock, replay, and production execution are equivalent.
- After a milestone, record what changed, what was tested, what failed, and the exact next action in `docs/PROGRESS.md`.
- On a later session, use the progress file and relevant source files to resume; do not restart or reread every document unnecessarily.
- When blocked on the local cluster, continue code, fixtures, tests, or documentation that does not depend on that blocker. Do not claim the blocked integration is complete.

Suggested progress-file fields: current milestone; environment facts; decisions and rationale; completed checks with dates; unresolved failures; agreed API budget and spend; Git branch/remote; next three actions. Do not store secrets there.

Keep `AGENTS.md` short. It should point to this brief, describe essential lab boundaries and verification commands as they become available, and reference the progress file for session resumption. Do not copy this entire brief into every prompt.

## 15. Research foundation and attribution

These sources informed the project direction. Verify the actual version and license of any code reused. Do not suggest that RackOps reproduces the full papers or matches their production results.

1. **Chen et al., AIOpsLab, MLSys 2025.** Interactive evaluation using deployed workloads, injected faults, and telemetry. Its failure analysis motivates bounded tools, compact observations, and healthy cases.
   - Paper: https://www.microsoft.com/en-us/research/wp-content/uploads/2024/10/AIOpsLab-1.pdf
   - Implementation: https://github.com/microsoft/AIOpsLab
2. **Chen et al., STRATUS, NeurIPS 2025.** Structured reliability workflows and Transactional No-Regression motivate explicit repair/verification/rollback stages. This small project does not inherit the paper's guarantees simply by implementing rollback.
   - Paper: https://papers.nips.cc/paper_files/paper/2025/file/47a6e9e2c3019f13ad94a0f259fe4970-Paper-Conference.pdf
3. **Jha et al., ITBench, ICML 2025.** Motivates outcome-based, repeatable evaluation of agents on operational tasks.
   - Paper: https://proceedings.mlr.press/v267/jha25a.html
4. **Pham et al., RCAEval, WWW Companion 2025.** Provides 735 labeled microservice failure cases. Useful for a later diagnosis-only extension; recorded telemetry does not validate an executed repair.
   - Paper: https://arxiv.org/abs/2412.17015
   - Implementation: https://github.com/phamquiluan/RCAEval
5. **Xiong et al., SuperBench, USENIX ATC 2024.** Connects reliability and proactive validation to real AI infrastructure. Hardware and GPU validation remain outside this MVP.
   - Paper: https://www.usenix.org/system/files/atc24-xiong.pdf

Alternatives considered but not selected: SustainDC (https://arxiv.org/abs/2408.07841) for simulated cooling/scheduling control, and Carbon-Aware Computing for Datacenters (https://arxiv.org/abs/2106.11750) for constrained workload shifting. Do not expand this project to include them.

Official setup and handoff references:

- Docker on Windows: https://docs.docker.com/desktop/setup/install/windows-install/
- kind quick start: https://kind.sigs.k8s.io/docs/user/quick-start/
- Codex milestone-based work: https://developers.openai.com/blog/run-long-horizon-tasks-with-codex
- Keeping repository instructions focused: https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra

## 16. Portfolio narrative

Explain the work as a local infrastructure reliability experiment inspired by published research. Distinguish engineering capability from production experience. Discuss why simple rules can outperform an agent on known faults, what evidence the agent needed, how erroneous actions were constrained, and what the evaluation cannot establish.

Resume template, to fill only after measurement:

> Built a Kubernetes incident-response agent harness with telemetry investigation, constrained remediation, rollback, and independent recovery verification; evaluated [N] held-out configurations across [R] runs against rule-based and tool-calling baselines, achieving [X]% verified recovery on repairable cases at [Y] median recovery time for successful attempts.

Never invent the bracketed values. Clearly state the denominator and any reduced scope.

## 17. Prompt to start or resume

**Start:** Read this master brief and help me implement RackOps in a dedicated project workspace. Begin with environment checks and the first working application milestone. Explain unfamiliar tools briefly. Continue useful local work while resolving GitHub setup and API-budget details, and maintain `docs/PROGRESS.md` as you go.

**Resume:** Read `docs/PROGRESS.md` and the relevant parts of `PROJECT_BRIEF.md`. Check the actual repository state, summarize the next milestone, and continue implementation and verification without restarting completed work.
