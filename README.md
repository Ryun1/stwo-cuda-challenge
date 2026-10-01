# Stwo CUDA Challenge

Optimize the production Cairo and circuit-recursion CUDA paths in
[`stwo-zig`](https://github.com/teddyjfpender/stwo-zig) on one H200. The ranked
workload starts with **already adapted** Starknet PIE inputs, proves each PIE,
wraps Cairo proofs in circuit verifier proofs, and folds consecutive leaves to
one recursive root. The judge owns the inputs, clock, memory measurement,
security settings, independent Cairo verification, and canonical root checks.

This is a standalone challenge repository, modeled on the contract/editable
surface/workflow split in [QSB](https://github.com/Layr-Labs/quantum-safe-bitcoin-challenge)
and the research-discussion habit in [sig.golf](https://github.com/Layr-Labs/sig.golf).
The pinned prover source is fetched into `workspace/stwo-zig`; participant source
changes are captured as a patch under `candidate/`. No production prover code
lives in this challenge repository's harness.
That source commit is on the upstream `main` branch (PR #204). Paths under
`/tmp` in development receipts are local build outputs or generated fixtures;
they are not required source checkouts. `./setup.sh` obtains the exact source
commit. Public inputs and retained reference proofs are under
[`data/`](data/README.md), with the scored fixture contract in
[`fixtures/public-v1.json`](fixtures/public-v1.json).

Start with [TASK.md](TASK.md). The fixed contract is [benchmark.json](benchmark.json),
the workload and proof obligations are in [spec/WORKLOADS.md](spec/WORKLOADS.md),
and the scoring and tradeoffs are in [spec/SCORING.md](spec/SCORING.md).
The specific upstream design choices are recorded in
[spec/REFERENCES.md](spec/REFERENCES.md). The exact boundary before enabling
the live H200 leaderboard is in [spec/ACTIVATION.md](spec/ACTIVATION.md).

Three rankings use the **same validated proofs and measurements**. The public
basket currently has six component-diverse PIEs, two fixed-leaf root folds
(two leaves and eight distinct contiguous leaves), and two full PIE-to-root
modes (serial and integrated batch):

| Track | Objective | Why it exists |
| --- | --- | --- |
| `latency` | Minimize the weighted geometric mean of adapted-input-to-publication time | Fastest usable H200 pipeline. |
| `memory` | Minimize the weighted geometric mean of whole-device peak bytes, with a latency guard | Make dense PIEs fit and enable later GPU choices. |
| `balanced` | Minimize normalized time × peak memory, with per-case guardrails | Explore the Pareto tradeoff; a capacity proxy, not a dollar-cost claim. |

Every score card publishes the uncompressed per-case `(time, memory)` ratios;
`harness/frontier.py` derives Pareto status across judged submissions.
Correctness is a hard gate for **all** tracks. The
ranked suite is fixed by a versioned, hash-pinned manifest; holdout inputs use
the same public shape classes. There is no score from a self-reported kernel
timer, a source-only static estimate, or an unverified proof.

## Development loop

1. Prepare a Linux CUDA/H200 workspace with Zig 0.15.2, CUDA/nvcc, Cargo,
   `nightly-2026-01-15`, Docker/NVIDIA Container Toolkit, and `git lfs pull`.
   Build and pin the [judge sandbox image](spec/H200_RUNBOOK.md), then set
   `STWO_SANDBOX_IMAGE` to its local SHA-256 image ID. `./setup.sh` creates separate
   pinned baseline and editable source checkouts; it does not download private
   PIEs.
2. Work in `workspace/stwo-zig` under the allowed CUDA source paths. Run
   relevant small local tests before a GPU trial.
3. Capture the source diff with `./scripts/capture-candidate.sh`. Optionally
   attach a prebuilt binary digest for the fast screening tier. The binary is
   never a substitute for source in a ranked submission.
4. Build both arms, the pinned Rust verifiers, and the canonical preprocessing
   asset with `./setup.sh --build`. Run a small `smoke` on the H200,
   then a complete one-pass `qualify`. A `rank` run performs three ABBA rounds
   and emits scores for every eligible track. Ranked service submissions require
   the trusted builder to rebuild the pinned source plus submitted patch.

On a prepared H200 host, the local loop is:

```sh
git lfs pull
./setup.sh
# Edit allowed CUDA source paths in workspace/stwo-zig.
./scripts/capture-candidate.sh
./setup.sh --build
./benchmark.sh --tier smoke --track balanced
```

Use `--tier qualify` for all cases once and `--tier rank` for paired scoring.
The benchmark defaults to the checked-in public inputs and setup assets under
`.cache/`; operator paths and the private manifest can be supplied with CLI
flags or the `STWO_*` variables shown in `.github/workflows/h200-rank.yml`.
The checked-in public files use Git LFS: run `git lfs pull` and
`python3 scripts/check_data.py` after cloning. In deployment the judge may
mount its own read-only content-addressed store with the same manifest-relative
paths. Run `python3 scripts/materialize_public.py --source workspace/stwo-zig
--out data/inputs --verify-only` to check the original public fixture contract
before spending GPU time. The canonical preprocessing
asset is generated from the pinned prover with `zig build
cairo-preprocessed-export -Doptimize=ReleaseFast` followed by
`zig-out/bin/cairo-preprocessed-export /absolute/path/preprocessed-canonical.bin
canonical`. Keep the 2 GiB asset outside Git.

Standalone PIE proofs use the pinned `stwo-cairo-official-verifier`. Registry
leaf proofs use the pinned Rust `verify_cairo_cuda_json` helper because their
Blake2s-M31/lifted proof shape is different. `./setup.sh --build` creates both
verifiers from the pinned baseline source; `--registry-cairo-verifier` can
override the latter path when using operator-managed assets.

Participants do not need the PIE API key. The operator creates a static
content-addressed bundle once, then hosts that directory over HTTPS:

```sh
python3 scripts/publish_public.py \
  --source data/inputs \
  --out ../stwo-cuda-challenge-public-bundle
python3 scripts/fetch_public.py \
  --base https://your-fixture-host.example/challenge/h200-v1 \
  --out data/inputs
```

The downloader checks the committed manifest digest and every blob SHA-256.
`--case-id` fetches only one case for a cheap smoke loop. The public bundle is
prepared locally; its HTTPS hosting remains part of deployment.

The service/runner design, artifact policy, isolation requirements, and H200
budget controls are in [spec/JUDGE.md](spec/JUDGE.md). The
[H200 operator runbook](spec/H200_RUNBOOK.md) gives the activation sequence.
The CPU-only intake prototype and trusted dispatcher are runnable locally:

```sh
python3 service/intake.py --source workspace/baseline \
  --state ../stwo-cuda-challenge-state --token-file /secure/path/intake-token \
  --max-intake-requests-24h 100
python3 service/build_worker.py --source workspace/baseline \
  --state ../stwo-cuda-challenge-state --submission-id ID
python3 service/dispatch.py --source workspace/baseline \
  --state ../stwo-cuda-challenge-state --submission-id ID \
  --repository teddyjfpender/stwo-cuda-challenge --tier smoke --dry-run
```

`POST /submissions` takes `{"repository":"https://github.com/OWNER/FORK",
"commit":"FULL_SHA"}` and an optional `artifact_sha256`. It returns a job ID
after patch validation, without building or reserving the H200. The worker
rebuilds ranked binaries from source; uploaded artifacts are stored for future
untrusted fast screening only. A real H200 deployment requires a fixture
object store, verifier binaries, self-hosted runner, isolation, an externally
provisioned receipt signing key, chosen GPU dispatch budgets, and operator
secrets outside Git. Intake's request limit is persistent across restarts.
This repo does not claim to operate a live public ranking service yet.

The [private staging repository](https://github.com/teddyjfpender/stwo-cuda-challenge)
has Discussions enabled. Once an operator configures the dedicated H200
runner and judge variables, removing `--dry-run` dispatches a built submission
to the serialized workflow. Smoke, qualify, and rank receipts remain available
by tier as a submission progresses.
The manual `CPU sandbox probe` workflow exercises the image and filesystem
boundary on a hosted Linux runner; H200 GPU proof parity remains a separate
activation gate.

Discussion prompts and the planned GitHub Discussions categories are in
[spec/DISCUSSIONS.md](spec/DISCUSSIONS.md). No benchmark source, proof blob,
API token, or private fixture belongs in a Discussion or submission PR.
