# Research foundation and attribution

RackOps is an original small local experiment. No code from the projects below
has been copied into this repository, and RackOps does not reproduce their full
systems or establish their reported results.

| Work | Idea relevant to RackOps | Boundary |
| --- | --- | --- |
| [AIOpsLab, Chen et al., MLSys 2025](https://www.microsoft.com/en-us/research/wp-content/uploads/2024/10/AIOpsLab-1.pdf) | Deployed workloads, fault injection, telemetry, and interactive agent evaluation belong together. | RackOps uses one disposable API and Redis, not the AIOpsLab benchmark. |
| [STRATUS, Chen et al., NeurIPS 2025](https://papers.nips.cc/paper_files/paper/2025/file/47a6e9e2c3019f13ad94a0f259fe4970-Paper-Conference.pdf) | Explicit diagnosis, mitigation, and regression checks motivate bounded stages and rollback. | A verified local rollback does not establish STRATUS's Transactional No-Regression specification. |
| [ITBench, Jha et al., ICML 2025](https://proceedings.mlr.press/v267/jha25a.html) | Outcome-based evaluation on operational tasks motivates an independent checker. | RackOps tests known synthetic local faults only. |
| [RCAEval, Pham et al.](https://arxiv.org/abs/2412.17015) | Labeled telemetry cases may later support diagnosis-only comparison. | Recorded telemetry cannot validate an executed repair; RCAEval is not in the MVP. |
| [SuperBench, Xiong et al., USENIX ATC 2024](https://www.usenix.org/system/files/atc24-xiong.pdf) | Proactive validation matters for infrastructure reliability. | RackOps performs no hardware, GPU, power, or cooling validation. |

Dependency and container images are installed from their own distributions at
build time, rather than vendored here. Their current package/image licenses
should be reviewed as part of a production redistribution process. The source
files authored for RackOps are released under the repository's MIT license.
