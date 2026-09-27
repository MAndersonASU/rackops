# Windows handoff: verify the existing installation first

Docker Desktop and WSL processes were found running during the first session.
The coding session could not execute/read the per-user Docker installation,
even after requesting folder-read permission. Do not reinstall based on that
failure alone. Use a normal, non-elevated PowerShell terminal to inspect it:

```powershell
wsl --version
wsl --list --verbose
$rackopsDockerBin = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin'
if (Test-Path -LiteralPath $rackopsDockerBin) {
    $env:PATH = "$rackopsDockerBin;$env:PATH"
}
docker version
docker info --format '{{.OSType}}'
kubectl version --client
kind version
```

Expected Docker mode is `linux`. This changes PATH for that terminal only.
If Docker cannot start, open Docker Desktop, finish any setup it requests, and
use its WSL 2 backend. WSL feature installation or an update can require an
administrator prompt or restart; complete those interactively if needed.
The official [Docker Windows guide](https://docs.docker.com/desktop/setup/install/windows-install/)
describes the supported installation modes and WSL checks.

If kind is missing, install it using the official
[kind quick start](https://kind.sigs.k8s.io/docs/user/quick-start/).
If kubectl is missing, follow the official
[Windows kubectl instructions](https://kubernetes.io/docs/tasks/tools/install-kubectl-windows/).
Do not change an existing non-lab Kubernetes context to run RackOps; its commands
explicitly target `kind-rackops` and `rackops-lab`.

Once those checks work, from this repository:

```powershell
$env:PATH = "$(Join-Path $PWD '.venv\Scripts');$env:PATH"
rackops doctor
rackops lab up
rackops lab inject
rackops lab recover
```

The first three lab steps may download images and consume several GiB of RAM.
The brief's 10–12 GiB WSL allowance is planning guidance, not a measured minimum.
Do not change `.wslconfig` or shut down WSL without considering other running work.

If startup partially fails, inspect `kind get clusters` and the explicit lab
namespace before retrying. An incomplete cluster without the lab identity label
is deliberately not adopted by `reset` or removed by the guarded `down` command.

GitHub is independent of local testing. When publication is due, authenticate with
`gh auth login -h github.com`, and agree the destination owner and visibility.
Never paste tokens into chat or checked-in files.
