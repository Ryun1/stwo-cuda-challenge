# Research discussions

Enable GitHub Discussions when the challenge is published. Recommended
categories: **Ideas and profiling** (open hypotheses), **Results and
reproductions** (public receipts and machine conditions), **Workload and
contract** (governance proposals), and **Help** (setup and debugging).
Pin a welcome post linking `TASK.md`, `spec/SCORING.md`, the current baseline
and the score-card schema. Prefer one mechanism per thread; include workload
IDs, the exact source commit, profiler data, before/after phase and memory
figures, and a falsifiable prediction. Link failed attempts too.

Discussions can propose changes to fixtures or scoring but cannot silently
change a live epoch. Contract changes require a reviewed PR, a new manifest
hash and baseline, and a new epoch. A discussion claim is never a judged score.
Public posts must not include API keys, private fixture URLs, unpublished PIE
bytes, proof blobs, or runner logs with secrets.
