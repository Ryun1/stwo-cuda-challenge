# Candidate execution boundary

The repository now includes a Docker/NVIDIA launcher and fails closed unless
the judge has a locally present image pinned by SHA-256. That launcher has
local plan tests but has **not** been qualified on an H200. Public ranking
stays disabled until the actual runner passes the denied-access and proof
parity tests below. The candidate controls allowed CUDA
source changes and their compiled prover binaries; the judge controls the
fixture manifest, reference outputs, verifiers, clock, NVML monitor, and
service credentials.
Each process gets a fresh case directory with case-local `HOME`, `TMPDIR`, and
`CUDA_CACHE_PATH`. The judge stages only this case's hash-checked inputs and
the two prover binaries plus pinned registry/program files. It mounts those
and the CUDA assets read-only, mounts only the case output directory writable,
and launches as UID 65532 with no network, no added capabilities, a read-only
root filesystem, and one assigned GPU. The expected proof/root digests and
private manifest stay outside the container. Docker creation is outside the
proof clock; attached start, execution, and publication are timed. The judge
retains the container ID and forcibly removes it on timeout.

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
equivalently restrictive GPU container, for candidate code. The remaining
H200 qualification must check GPU device permissions, CUDA runtime libraries,
read-only asset use, output directory ownership, and a host-side output quota.
The 900-second process timeout, 1 GiB per-file limit, and disabled core dumps
are implemented, but the total output quota must be
enforced on the runner's writable volume before activation. The same boundary
applies to participant-supplied fast-screening
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
