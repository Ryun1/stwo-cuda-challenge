---
name: stwo-cuda-challenge
description: Help a participant set up, optimize, validate, and package a CUDA Cairo/recursion candidate for this repository's pinned H200 autoresearch challenge. Use for work on the challenge's candidate prover, measurements, or submission workflow.
---

# Stwo CUDA Challenge

Work from this repository's root. Read [TASK.md](../../TASK.md),
[spec/WORKLOADS.md](../../spec/WORKLOADS.md), and
[spec/SCORING.md](../../spec/SCORING.md), and
[spec/SUBMISSIONS.md](../../spec/SUBMISSIONS.md) before changing the candidate. The
versioned contract in [benchmark.json](../../benchmark.json) fixes the source
commit, editable paths, workloads, and security profile.

Use `python3 challenge.py --help` for the participant CLI. Run `python3 challenge.py setup` to create the ignored pinned editable checkout at `./workspace/stwo-zig/` (singular `workspace`), then `python3 challenge.py paths` to print its absolute location. [spec/CODE_MAP.md](../../spec/CODE_MAP.md) gives exact CUDA files and purposes; edit only the five `benchmark.json` directories. Use `capture` to produce `candidate/changes.patch`; keep
`candidate/NOTES.md` current with the hypothesis, focused checks, and measured
results. The judge rebuilds from that patch, so a local binary is never the
ranked submission.

Use [GitHub Discussions](https://github.com/teddyjfpender/stwo-cuda-challenge/discussions)
to compare design alternatives and profiler evidence. An Ideas thread should
name a measurable bottleneck, mechanism, prediction, and smallest falsifying
case; Show and tell is for verified public measurements. Link useful threads
from the eventual PR. Never post private fixtures, keys, or proof blobs.

Prefer a focused local check before a public H200 smoke case. On a prepared
H200 host, use `setup --build`, then `benchmark --tier smoke`, followed by
`benchmark --tier qualify` for the full basket. Use `--tier rank` only after
qualification. Every case must produce its canonical, independently verified
proof at the fixed security settings. Consult [README.md](../../README.md) for
host prerequisites and [spec/H200_RUNBOOK.md](../../spec/H200_RUNBOOK.md) for
operator-only H200 setup.

Keep proof-stage telemetry separate from ranked adapted-input-to-publication
wall time. The measured phases are in [data/reports](../../data/reports/README.md).
The current [activation record](../../spec/ACTIVATION.md) describes what must
be enabled before a live ranked submission can run. Do not present local or
direct H200 results as leaderboard scores.

Complete `candidate/NOTES.md`, commit and push it with
`candidate/changes.patch` to a challenge fork, and open a PR against the
challenge repository for review. Explain changed paths, mechanism, before and
after public time and peak memory, checks, regressions, tradeoffs, any model or
harness used, and related Discussions. Once intake is live, separately submit
the fork's HTTPS URL and full immutable commit SHA to `POST /submissions` at
the operator-provided endpoint. Intake currently does not consume PR numbers
or start automatically on PR open. The trusted builder applies the patch and
the judge issues smoke, qualify, and rank receipts; only a signed rank receipt
is a leaderboard claim. [spec/JUDGE.md](../../spec/JUDGE.md) defines those
stages. The current repository does not publish an intake endpoint.
