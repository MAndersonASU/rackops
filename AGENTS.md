# RackOps contributor instructions

Read `docs/PROGRESS.md` first, then relevant sections of `PROJECT_BRIEF.md`.
Preserve the distinction between real Kubernetes runs, fixtures, and paid LLM runs.
Use disposable data only. Mutations must target the dedicated `kind-rackops`
context, `rackops-lab` namespace, named resources, and approved fields.
Never expose shell, Docker, administrator credentials, or scenario truth to a
runtime agent. The trusted lab CLI is not a runtime-agent tool.
Do not spend API money or publish without the user's agreed scope.
Run `python -m ruff check .`, `python -m ruff format --check .`, and
`python -m pytest`. Record actual checks and blockers in `docs/PROGRESS.md`.
Do not mark a milestone complete from fixtures alone.
