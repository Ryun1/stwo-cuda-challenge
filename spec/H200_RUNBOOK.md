# H200 operator runbook

This runbook is for the private staging challenge. The local contract checks
pass, but no H200 judge runner is registered yet. Do not dispatch a judged
submission until the live activation gates in [`ACTIVATION.md`](ACTIVATION.md)
are satisfied. A single H200 is reserved for one run at a time; all CPU builds,
fixture transfers, and hash checks happen before its timed proof work.

## Prepare the host once

1. Use one exclusive H200 SXM with the device capacity in `benchmark.json`.
   Install Zig 0.15.2, CUDA/nvcc, Cargo, `nightly-2026-01-15`, Git LFS, and
   the GitHub CLI. Keep service state, private fixtures, credentials, and the
   2 GiB canonical preprocessing asset outside this repository.
2. Clone the challenge, then run `git lfs pull`, `./setup.sh --build`, and
   `python3 scripts/check_data.py`. This fetches the pinned prover, builds the
   baseline and local-workspace CUDA products and both pinned Rust verifiers,
   generates the canonical preprocessing asset, and checks every public file.
   The baseline and
   candidate source roots and binary hashes must match their build
   attestations before ranking.
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
4. Register one online self-hosted runner with the default `self-hosted` label
   and `h200-stwo-challenge`. Configure all eight repository variable names
   used in `.github/workflows/h200-rank.yml` with nonempty paths. Run
   `python3 service/activation.py --repository OWNER/REPO`; it prints no
   variable values and must pass before dispatch. Qualify process isolation,
   outbound-network blocking, read-only fixture mounts, and receipt signing
   separately before opening the public leaderboard. The required access
   matrix and denied-access probes are in [`ISOLATION.md`](ISOLATION.md).

## Qualify the exact workflow

1. Start `service/intake.py` on loopback with an external state directory.
   Submit a source commit, then run `service/build_worker.py` for its returned
   ID. Uploaded binaries are not run by the ranked judge; the worker rebuilds
   the pinned source plus allowed patch outside the H200 timing interval.
2. Dispatch `smoke`, then `qualify`, then `rank` through
   `service/dispatch.py`. Each tier requires the prior receipt. The workflow
   carries an immutable dispatch attempt ID, measures one exclusive H200,
   verifies every proof and root, and publishes a redacted receipt. The rank
   tier performs three paired ABBA rounds and writes all eligible score files
   from the same measurements.
3. Inspect the complete judge-owned evidence, the public redacted receipt,
   per-case time and memory ratios, A/A dispersion, bootstrap intervals, and
   peak device-memory samples. Run the public and private baskets against the
   pinned baseline first; no historical H100/H200 time is a score denominator.
   If a workflow was cancelled before receipt publication, run
   `service/reconcile.py` so the completed GitHub run releases its dispatch
   slot. A run not yet visible in GitHub stays reserved for operator review.
4. Shut down the paid H200 host when proof qualification is complete. Retain
   immutable evidence and receipts in the external service store, and add
   operator signing before public release. Keep generated proofs and logs
   outside Git. Public reference outputs are already
   under `data/outputs` and are checked by `scripts/check_data.py`.
