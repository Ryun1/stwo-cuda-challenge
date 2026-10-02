---
name: stwo-cuda-challenge
description: Help a participant set up, optimize, validate, and package a CUDA Cairo/recursion candidate for this repository's pinned H200 autoresearch challenge. Use for work on the challenge's candidate prover, measurements, or submission workflow.
---

# Stwo CUDA Challenge

Work from this repository's root. Read [TASK.md](../../TASK.md),
[spec/WORKLOADS.md](../../spec/WORKLOADS.md), and
[spec/SCORING.md](../../spec/SCORING.md) before changing the candidate. The
versioned contract in [benchmark.json](../../benchmark.json) fixes the source
commit, editable paths, workloads, and security profile.

Use `python3 challenge.py --help` for the participant CLI. Run `setup` to create
the pinned editable checkout, then modify only `workspace/stwo-zig` paths listed
in `benchmark.json`. Use `capture` to produce `candidate/changes.patch`; keep
`candidate/NOTES.md` current with the hypothesis, focused checks, and measured
results. The judge rebuilds from that patch, so a local binary is never the
ranked submission.

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

When intake is live, commit and push `candidate/changes.patch` and
`candidate/NOTES.md` to an immutable GitHub commit. Submit its HTTPS repository
URL and full commit SHA to `POST /submissions` at the operator-provided intake
endpoint. The current repository does not publish such an endpoint. The trusted
builder applies the patch and the judge issues smoke, qualify, and rank
receipts; [spec/JUDGE.md](../../spec/JUDGE.md) defines those stages.
