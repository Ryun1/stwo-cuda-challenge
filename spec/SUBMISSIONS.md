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
   root. Setup creates the pinned `workspace/stwo-zig` checkout.
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
4. If you add a new allowed CUDA source file, first stage it in the pinned
   checkout with `git -C workspace/stwo-zig add -N PATH` so Git includes it in
   the diff. Run `python3 challenge.py capture`. It writes
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

The **judge submission is a separate step**. Once the intake endpoint is
deployed, send the fork's HTTPS repository URL and the full, immutable commit
SHA containing the patch and notes to `POST /submissions`. The service returns
a submission ID. It currently accepts a Git commit, **not a PR number**, and
does not automatically discover, require, or create a PR. Keep the PR's head
at the submitted SHA or record the submitted SHA in the PR when adding more
commits. Link the submission ID and later public signed receipt in the PR.
The trusted builder and H200 judge run only after operator dispatch; opening a
PR does not trigger paid GPU work. No public intake endpoint is live yet.

A complete candidate submission includes:

- A nonempty `candidate/changes.patch` affecting only allowed CUDA paths and
  applying to the pinned source commit.
- `candidate/NOTES.md` with a mechanism, affected paths, focused and public
  validation, measured time and memory, correctness evidence, tradeoffs,
  model/harness attribution, and relevant Discussion links.
- An immutable fork commit; for human review, a PR linking that commit and
  explaining the claimed improvement. A claim remains unranked until the
  operator publishes an independently verified, signed rank receipt.

The current intake authentication uses a shared bearer token and global rate
limit. It is **not** yet a multi-user identity system; public self-service
access requires an authenticated front door with per-user quotas and a PR to
submission mapping. See [`OPERATIONS.md`](OPERATIONS.md).
