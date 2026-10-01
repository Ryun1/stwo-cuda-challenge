# Judge and validation service design

## Submission and trust boundary

A submission is an immutable public GitHub commit containing `candidate/changes.patch`
against the pinned `stwo-zig` commit and `candidate/NOTES.md`. Only paths listed
in `benchmark.json` may change. The intake service checks patch paths, file
types, size, base commit, syntax, and provenance without executing candidate
code. It records the exact submitted commit and a content digest. Symlinks,
submodules, generated build outputs, modifications to tests/harness/verifiers,
and executable scripts outside the allowed source are rejected.

An optional build artifact may accompany a submission **only for a future
fast screening tier**. Intake can receive it by digest and stores it outside
Git; the current judge does not execute it. Screening must run in the same
unprivileged GPU sandbox with no secrets or write access to fixtures, label
results `untrusted-build`, and never rank or promote them. A source-only
submission takes the normal path.

The trusted build worker checks out the pinned source, applies the allowed patch,
builds ReleaseFast CUDA products, runs focused source tests, and stores an
artifact keyed by `(contract epoch, base commit, patch digest, toolchain,
target SM, build flags)`. This runs on CPU capacity, not on the H200 clock.
The H200 judge consumes only that immutable built artifact, selects its
fixture set after source fixation, and performs the proof runs. A cache hit
may skip recompilation only when **all** key fields match. The trusted
verifier and score code are never built from participant source.

The H200 service uses one job per exclusive device, an unprivileged uid,
read-only fixture mount, blocked outbound network, bounded process tree,
runtime/output limits, and a fresh work directory. It refuses a shared or
busy GPU. The judge's NVML monitor and wall clock run outside the candidate
container/uid. Kill and discard the entire process group on timeout.

## Validation tiers

1. **Intake (<1 min, no GPU):** source-policy and manifest checks, hashes,
   patch apply dry run, candidate ID. Duplicate digest returns cached status.
2. **Build/smoke (CPU builder; optional small GPU smoke):** compile and focused
   tests, one public Cairo case and one recursion case, independent verification.
3. **Qualify (H200):** public basket plus private holdout, exact security and
   output gates, stage receipt, one run per case. This filters failures cheaply.
4. **Rank (H200):** fresh A/A baseline calibration and at least three paired
   ABBA rounds; score all tracks from the same measurements. Publish
   content-addressed receipts and public per-case metrics after private case
   identifiers are redacted. Cryptographic operator signatures are a launch
   requirement, not provided by the local prototype.

The CPU-only intake implementation is `service/intake.py`. It exposes
`POST /submissions` with a GitHub HTTPS repository, full commit SHA, and
optional artifact SHA-256; `PUT /submissions/{id}/artifact` for a declared
artifact; `GET /submissions/{id}` for status; and
`GET /submissions/{id}/receipt` for a redacted immutable receipt. It accepts
only a regular patch and notes file from the submitted commit, bounds their
size, validates the patch against a clean pinned checkout, and returns a
digest-keyed job without touching a GPU. `service/build_worker.py` applies
that patch in a fresh checkout and produces a trusted build attestation.
`service/publish_receipt.py` joins a completed H200 run to the staged job.
The GitHub `workflow_dispatch` is an operator path for that judge; it is not
triggered for every PR. Deployment still needs authentication, account rate
limits, GPU-minute budgets, isolation, signing, and an operator queue policy.
Promotion is manual and requires fresh ranked evidence. A public Discussion
is for learning, not an intake endpoint.

## Activation checklist

Before a leaderboard goes live: publish the public fixture manifest and blobs;
hold back distinct private fixtures; pin and test official Rust Cairo and
recursion verifiers; calibrate the H200 baseline on the exact source commit;
run A/A variance and NVML sampling checks; install a dedicated self-hosted
runner and artifact store; verify sandbox isolation and cost limits; enable
GitHub Discussions and the separate queue service. No cloud resources or
credentials are embedded here. The workflow template stays manual until the
operator connects the runner.
