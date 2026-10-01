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
builds ReleaseFast CUDA products, runs focused source tests, and records the
binary hashes against the source commit, patch digest, and toolchain. This
runs on CPU capacity, outside the H200 measurement clock. Intake deduplicates
identical patches; the current worker does not yet share finished binaries
across different submissions. A future trusted artifact cache may skip a build
only when the epoch, source, patch, toolchain, target SM, and flags all match.
The H200 judge uses only the trusted worker's attested binaries, selects its
fixture set after source fixation, and performs the proof runs. The trusted
verifier and score code are never built from participant source.

The H200 service must use one job per exclusive device, an unprivileged uid,
read-only fixture mount, blocked outbound network, bounded process tree,
runtime/output limits, and a fresh work directory. It refuses a shared or
busy GPU. The judge's NVML monitor and wall clock run outside the candidate
container/uid. Kill and discard the entire process group on timeout. The
candidate subprocess receives only a fixed runtime environment allowlist and
the three judge-owned CUDA asset settings, never the host's service tokens.
Authenticated submission and artifact-upload requests are limited over a
rolling 24-hour window in SQLite before the service fetches Git objects or
accepts an upload. Live dispatch also requires an
operator-chosen rolling GPU-minute budget and per-submitter-repository attempt
budget. Each accepted attempt reserves the workflow's full 90-minute timeout;
failed and cancelled attempts continue to count. This conservative accounting
bounds worst-case spend without trusting a candidate timer. The shared intake
token provides a global request limit; separate account identities and quotas
would be needed before opening self-service submissions to multiple users.
The exact file/device/network boundary and its required H200 probe are in
[`ISOLATION.md`](ISOLATION.md). That boundary is an activation gate, not a
claim that the current local prototype is already isolated.

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
   identifiers are redacted. The publisher signs each immutable receipt with
   an external Ed25519 operator key; public verification needs the separately
   authenticated operator public key. The H200 deployment must keep that key
   inaccessible to the candidate sandbox.

The CPU-only intake implementation is `service/intake.py`. It exposes
`POST /submissions` with a GitHub HTTPS repository, full commit SHA, and
optional artifact SHA-256; `PUT /submissions/{id}/artifact` for a declared
artifact; `GET /submissions/{id}` for status; and
`GET /submissions/{id}/receipt` for the latest redacted receipt, and
`GET /submissions/{id}/receipts/{smoke|qualify|rank}` for a tier's latest
content-addressed receipt. The corresponding `/signature` suffix returns its
detached Ed25519 signature. It accepts
only a regular patch and notes file from the submitted commit, bounds their
size, validates the patch against a clean pinned checkout, and returns a
digest-keyed job without touching a GPU. `service/build_worker.py` applies
that patch in a fresh checkout and produces a trusted build attestation.
`service/publish_receipt.py` joins a completed H200 run to the staged job only
when the workflow judge step succeeded. A failed judge step cannot promote a
scorecard left on disk after an eligibility guard or later validation failure.
Malformed or mismatched judge artifacts also fail the attempt and release its
single-GPU queue slot.
`service/dispatch.py` checks tier prerequisites and allows one active H200
dispatch at a time before triggering the manual GitHub Actions workflow.
It first checks that the GitHub repository has the required nonempty judge
variables and an idle online runner with both `self-hosted` and
`h200-stwo-challenge` labels. This prevents an unusable workflow from taking
the single GPU queue slot.
Each workflow run carries its immutable dispatcher attempt ID. Publication can
only complete that exact active attempt; a delayed older run cannot update a
retry. If a workflow is cancelled before the publication step, run
`python3 service/reconcile.py --state STATE --source BASELINE --repository
OWNER/REPO` to compare active attempts with terminal GitHub Actions runs and
release their queue slots. An attempt with no visible matching run stays active
until the operator establishes what happened to the dispatch.
The workflow is not triggered for every PR. Deployment still needs
authentication, account rate limits, GPU-minute budgets, isolation, signing,
and an operator queue policy.
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

`scripts/publish_public.py` produces a static content-addressed directory,
and `scripts/fetch_public.py` verifies it against the committed manifest. The
public bundle can be hosted without exposing the PIE API key. The local bundle
alone is not a live public endpoint.
