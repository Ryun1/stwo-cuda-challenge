# Candidate execution boundary

The current repository specifies this boundary but does not yet provide a
qualified Linux/NVIDIA sandbox launcher. Public ranking stays disabled until
the H200 runner enforces and tests it. The candidate controls allowed CUDA
source changes and their compiled prover binaries; the judge controls the
fixture manifest, reference outputs, verifiers, clock, NVML monitor, and
service credentials.

| Resource | Candidate access during one timed case |
| --- | --- |
| Candidate Cairo and circuit CUDA binaries, pinned registry and program JSON, required runtime libraries | Read and execute only. |
| Current case CPI, preimage, or fold leaf inputs | Read-only; expose the files for this case, not the parent fixture store. |
| Canonical preprocessing asset and authenticated CUDA artifact bundle | Read-only. |
| Fresh case output and temporary directory | Write. Published files are collected by the judge after process exit. |
| Private manifest, expected proof/root digests, other holdout inputs, `data/outputs`, Rust verifiers, score code, service database, GitHub/Runpod credentials | No access. |
| H200 device | Access to the single assigned GPU; the judge samples NVML outside the candidate boundary. |
| Network and host process table | No outbound network, no access to judge processes or their environment. |

Use a distinct unprivileged identity and a filesystem/mount namespace, or an
equivalently restrictive GPU container, for candidate code. The judge stages
only authenticated input bytes for the selected case. It starts a fresh
process tree, applies output-size and time limits, and kills the entire tree
on timeout. The same boundary applies to participant-supplied fast-screening
artifacts if that optional tier is ever enabled; such artifacts remain
untrusted and cannot produce ranked receipts.

Before activating the runner, exercise the boundary with a probe binary that
tries to read a judge-only sentinel, list a sibling holdout case, read service
tokens, connect to an external address, write a fixture, and access another
GPU. Every attempt must fail. Then run the pinned baseline proof for one PIE,
one fold, and one full pipeline case inside the boundary, and require the
same independently verified proof bytes as the unsandboxed baseline. Record
the launcher version, UID/mount/network policy, device mapping, and test
receipt outside Git. A sandbox that blocks a valid proof or exposes any
judge-only resource does not qualify this epoch.
