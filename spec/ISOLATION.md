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
read-only asset use, output directory ownership, and the host-side output quota.
The 900-second process timeout, 1 GiB per-file limit, and disabled core dumps
are implemented. The writable case directory now sits on a fresh fixed-size
2 GiB ext4 loopback filesystem, with its image outside candidate mounts.
Its fixed filesystem capacity bounds the total of all proof files, reports,
logs, and scratch files. Candidate stdout is drained to a separate judge-owned
log capped at 64 MiB; exceeding that cap fails the case. The judge copies
retained outputs after the candidate exits, preserves links as links, and
removes the mount and image. The actual
Linux runner must pass a forced-ENOSPC probe before activation. The same boundary
applies to participant-supplied fast-screening
artifacts if that optional tier is ever enabled; such artifacts remain
untrusted and cannot produce ranked receipts.

Run `python3 scripts/probe_sandbox.py --image "$STWO_SANDBOX_IMAGE"` on the
Linux runner. Its CPU probe checks the actual Docker mounts, UID, private PID
namespace, hidden judge sentinel and sibling input, absent service token and
Docker socket, blocked outbound network, read-only input and preprocessing
asset, writable case output, and a 64 MiB output volume rejecting a larger
write with ENOSPC. A separate manually dispatched
`sandbox-probe.yml` workflow runs the same probe on a hosted Linux CPU using a
disposable Ubuntu base image; it does not qualify NVIDIA access or the
production image. The hosted [quota probe run](https://github.com/teddyjfpender/stwo-cuda-challenge/actions/runs/36923016520)
passed all eleven checks on Linux as UID 65532, including the forced ENOSPC
and retained-output checks. On the H200, also try to access another GPU. Every denied
attempt must fail. Then run the pinned baseline proof for one PIE,
one fold, and one full pipeline case inside the boundary, and require the
same independently verified proof bytes as the unsandboxed baseline. Record
the launcher version, UID/mount/network policy, device mapping, and test
receipt outside Git. A sandbox that blocks a valid proof or exposes any
judge-only resource does not qualify this epoch.
