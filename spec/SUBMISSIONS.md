# Participant workflow and submissions

The goal is to make the pinned H200 CUDA prover faster or use less device
memory **across the full Cairo PIE, recursive-fold, and PIE-to-root basket**.
Every required proof must still verify with the pinned independent verifier,
match its expected public output, use the canonical security profile, and have
no CPU proving fallback. The actual `h200-v1` score measures adapted-input to
published-proof wall time and whole-device peak memory. Read
[`WORKLOADS.md`](WORKLOADS.md) and [`SCORING.md`](SCORING.md) before optimizing.

## Research and design

Use [GitHub Discussions](https://github.com/teddyjfpender/stwo-cuda-challenge/discussions)
to compare architectures, profiler findings, memory plans, and failed as well
as successful experiments. Start an **Ideas** thread for a falsifiable design
hypothesis, **Q&A** for setup or verification help, and **Show and tell** for
reproducible public measurements. Link relevant threads from the eventual PR;
discussion is encouraged, not a prerequisite to run local tests. Keep private
holdouts, credentials, proof blobs, and unpublished inputs out of Discussions
and PRs. [`DISCUSSIONS.md`](DISCUSSIONS.md) describes the forms and evidence.

## Edit and validate

1. Fork this challenge repository. Run `git lfs pull`,
   `python3 challenge.py check-data`, and `python3 challenge.py setup` from its
   root. Setup creates the pinned `./workspace/stwo-zig/` checkout (singular `workspace`; ignored in Git). Run `python3 challenge.py paths` to print its absolute location. [CODE_MAP.md](CODE_MAP.md) names specific CUDA entry points.
2. Edit production prover code **only** under these `benchmark.json`
   `editablePaths` in `workspace/stwo-zig`:

   | Path | Typical work |
   | --- | --- |
   | `src/backends/cuda/` | Device runtime, allocation, kernels, scheduling, transfers. |
   | `src/integrations/cairo_cuda/` | Cairo witness, AIR, proof execution, ingress and publication. |
   | `src/integrations/circuit_cuda/` | CUDA circuit execution, wrap and fold integration. |
   | `src/products/cairo_cuda/` | Cairo CUDA product wiring and reporting. |
   | `src/products/circuit_recursion_cuda/` | Recursive CUDA product wiring and reporting. |

   CPU, Metal, and Rust code may inform a design but are outside the candidate
   edit surface. Do not change the challenge's fixture manifest, security,
   verifier, scoring, timers, or judge. The capture command refreshes derived
   CUDA manifests; do not hand-edit them.
3. Use the smallest relevant compile or focused test, then a public smoke
   case. On a prepared H200, run `python3 challenge.py setup --build` and
   `python3 challenge.py benchmark --tier smoke --track balanced`. Run
   `--tier qualify` for the complete basket when the focused checks pass;
   use `--tier rank` for paired measurements. Record the exact case, hardware,
   samples, end-to-end time, peak device bytes, proof checks, and regressions.
   Local measurements are research evidence, not leaderboard scores.
4. Run `python3 challenge.py capture` after editing. It automatically includes
   new files under the allowed CUDA paths and writes
   `candidate/changes.patch` from the allowed source diff and checks that it
   applies to the pinned commit. Fill in `candidate/NOTES.md`.

## Reviewable PR and judged submission

Push `candidate/changes.patch` and `candidate/NOTES.md` to your **fork of this
challenge repository** and open a PR against its `main` branch. The PR is the
human-review surface: describe the bottleneck, design, changed CUDA paths,
public measurements and proof checks, tradeoffs, model/harness attribution,
and related Discussions. GitHub's PR template prompts for these items. The
patch contains the production source changes; `workspace/`, generated proofs,
logs, and binaries are not PR artifacts. A submission PR need not be merged
into the challenge's `main` branch to be judged; accepted code can later be
applied or rebased into upstream `stwo-zig` separately.

For this internal challenge, **the PR is enough to enter the operator's daily
queue**. An operator reviews it and applies the `ready-to-judge` label. The
batch collector freezes that PR's full head SHA, reads the patch and notes
from that commit, validates them through immutable intake, and records the PR
number, SHA, and submission ID together. Pushing another commit creates a new
candidate; the old judged result still belongs to its original SHA. A PR does
not trigger paid GPU work automatically. The operator starts the H200 batch
and publishes independently verified signed receipts afterward. No public
intake endpoint or participant API key is needed for this workflow.

A complete candidate submission includes:

- A nonempty `candidate/changes.patch` affecting only allowed CUDA paths and
  applying to the pinned source commit.
- `candidate/NOTES.md` with a mechanism, affected paths, focused and public
  validation, measured time and memory, correctness evidence, tradeoffs,
  model/harness attribution, and relevant Discussion links.
- An immutable fork commit; for human review, a PR linking that commit and
  explaining the claimed improvement. A claim remains unranked until the
  operator publishes an independently verified, signed rank receipt.

The standalone HTTP intake remains available for a future self-service mode,
but its shared bearer token is not a participant credential. The manual PR
batch and its setup are in [`OPERATIONS.md`](OPERATIONS.md).
