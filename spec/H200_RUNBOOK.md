# H200 operator runbook

This runbook is for the private staging challenge. The local contract checks
pass, but no H200 judge runner is registered yet. Do not dispatch a judged
submission until the live activation gates in [`ACTIVATION.md`](ACTIVATION.md)
are satisfied. A single H200 is reserved for one run at a time; all CPU builds,
fixture transfers, and hash checks happen before its timed proof work.

## Prepare the host once

1. Use one exclusive H200 SXM with the device capacity in `benchmark.json`.
   Install Zig 0.15.2, CUDA/nvcc, Cargo, `nightly-2026-01-15`, Git LFS,
   OpenSSL with Ed25519 support, Docker Engine, the
   [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html),
   GitHub CLI, `e2fsprogs`, and `util-linux`. The judge process must run as
   root or have passwordless `sudo` for mounting, unmounting, and chmod on its
   own 2 GiB per-case ext4 output images. Keep service state,
   private fixtures, credentials, and the
   2 GiB canonical preprocessing asset outside this repository.
   `./setup.sh --build` resolves the explicit pinned CUDA build options from
   `nvcc`, `g++`, `ar`, and the toolkit's `lib64`, targeting SM 90. Set
   `STWO_CUDA_NVCC`, `STWO_CUDA_HOST_CXX`, `STWO_CUDA_AR`, `STWO_CUDA_HOME`,
   `STWO_CUDA_LIBRARY_DIR`, or the host runtime path overrides if auto-detection
   differs; `STWO_CUDA_BUILD_JOBS` defaults to four.
2. Clone the challenge, then run `git lfs pull`, `./setup.sh --build`, and
   `python3 scripts/check_data.py`. This fetches the pinned prover, builds the
   baseline and local-workspace CUDA products and both pinned Rust verifiers,
   generates the canonical preprocessing asset, and checks every public file.
   The baseline and
   candidate source roots and binary hashes must match their build
   attestations before ranking.
   Build `harness/sandbox.Dockerfile` from an NVIDIA CUDA runtime base pinned
   by repository digest:

   ```sh
   docker build -f harness/sandbox.Dockerfile \
     --build-arg CUDA_RUNTIME_IMAGE='nvidia/cuda:VERSION-runtime-ubuntu24.04@sha256:BASE_DIGEST' \
     -t stwo-judge:h200-v1 .
   ```

   Replace the placeholders with the qualified CUDA runtime version and full
   base digest. Record the local image ID returned by
   `docker image inspect --format '{{.Id}}' IMAGE_TAG`. Set
   `STWO_SANDBOX_IMAGE` to that `sha256:` ID. The judge refuses a mutable tag
   or an image absent from the local daemon. First run
   `python3 scripts/probe_sandbox.py --image "$STWO_SANDBOX_IMAGE"` on the host.
   Verify the exact image and driver
   combination with one sandboxed PIE, fold, and full-pipeline proof before
   ranking; local plan tests alone do not qualify it.
3. Copy the separately held ranked fixture store and manifest to read-only
   judge-owned paths. Check every digest before the H200 proof loop:

   ```sh
   python3 harness/run_arm.py --source workspace/baseline \
     --fixtures "$STWO_FIXTURE_ROOT" --manifest "$STWO_RANKED_MANIFEST" \
     --preprocessed .cache/preprocessed-canonical.bin \
     --artifact-dir .cache/cuda-artifacts \
     --cairo-verifier .cache/rust-official/release/stwo-cairo-official-verifier \
     --out .runs/preflight --round 0 --preflight
   ```

   Never put private case names, expected digests, or fixture paths in GitHub
   Discussions or a submission repository.
4. Generate an Ed25519 operator key outside this repository and service state,
   readable only by the judge identity. Publish its public half through an
   authenticated channel and retain the public-key digest for this epoch.
   `openssl genpkey -algorithm ED25519 -out /secure/path/operator-key.pem` and
   `openssl pkey -in /secure/path/operator-key.pem -pubout -out operator-public.pem`
   generate the key pair; restrict the private file to mode `0600`.
   Configure `STWO_RECEIPT_SIGNING_KEY` with the private-key **path**, not key
   bytes. The publisher signs the exact receipt JSON and serves a detached
   signature; verify it with `python3 service/receipt_signature.py --receipt
   RECEIPT.json --signature RECEIPT.signature.json --public-key operator-public.pem`.
   Candidate sandbox qualification must precede use of the key on an H200 job.
5. Register one online self-hosted runner with the default `self-hosted` label
   and `h200-stwo-challenge`. Configure all ten repository variable names
   used in `.github/workflows/h200-rank.yml` with nonempty paths. Run
   `python3 service/activation.py --repository OWNER/REPO`; it prints no
   variable values and must pass before dispatch. Qualify process isolation,
   outbound-network blocking, read-only fixture mounts, and receipt signing
   separately before opening the public leaderboard. The required access
   matrix and denied-access probes are in [`ISOLATION.md`](ISOLATION.md).

## Qualify the exact workflow

1. Start `service/intake.py` on loopback with an external state directory and
   an explicit `--max-intake-requests-24h` limit (for example, `100`).
   Submit a source commit, then run `service/build_worker.py` for its returned
   ID. Uploaded binaries are not run by the ranked judge; the worker rebuilds
   the pinned source plus allowed patch outside the H200 timing interval.
2. Dispatch `smoke`, then `qualify`, then `rank` through
   `service/dispatch.py`, passing `--max-gpu-minutes-24h` and
   `--max-repository-attempts-24h` on each live call. For example, `540` and
   `3` allow at most six 90-minute reservations globally and three attempts
   from one repository in any rolling day. Failed and cancelled attempts count
   conservatively. Each tier requires the prior receipt. The workflow checks
   out the event's exact commit and atomically claims its dispatch against the
   first GitHub run ID before measuring one exclusive H200,
   verifies every proof and root, and publishes a redacted receipt. The rank
   tier performs three paired ABBA rounds and writes all eligible score files
   from the same measurements.
3. Inspect the complete judge-owned evidence, the public redacted receipt,
   per-case time and memory ratios, A/A dispersion, bootstrap intervals, and
   peak device-memory samples. Run the public and private baskets against the
   pinned baseline first; no historical H100/H200 time is a score denominator.
   If a claimed workflow was cancelled before receipt publication, run
   `service/reconcile.py` so the exact completed GitHub run releases its
   dispatch slot. An unclaimed attempt or a run not yet visible in GitHub
   stays reserved for operator review.
4. Shut down the paid H200 host when proof qualification is complete. Retain
   immutable evidence and signed receipts in the external service store. Keep
   generated proofs and logs outside Git. Public reference outputs are already
   under `data/outputs` and are checked by `scripts/check_data.py`.
