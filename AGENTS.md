# Agent instructions

Read `TASK.md`, `spec/WORKLOADS.md`, `spec/SCORING.md`, and
`spec/SUBMISSIONS.md` before changing code. For the participant CLI, read
`skills/stwo-cuda-challenge/SKILL.md`.
The performance target is the full CUDA proving path on H200 for every fixed
case. For a **candidate submission**, edit only the pinned prover source in
`workspace/stwo-zig` under the `editablePaths` in `benchmark.json`. Capture changes into
`candidate/changes.patch` with `scripts/capture-candidate.sh`; include an
explanation and measured results in `candidate/NOTES.md`.

Use GitHub Discussions to debate architecture and design patterns, publish
reproducible public profiling results, and ask setup or verification questions.
The Ideas, Show and tell, and Q&A forms are described in `spec/DISCUSSIONS.md`.
Link relevant threads in the eventual submission PR. Discussion participation
does not replace focused tests, independent proof checks, or the H200 judge.

Keep short iteration loops: compile and test the touched CUDA layer first,
then one public H200 smoke case, then the complete qualification basket.
Measure external process time and whole-device memory; use backend phase
telemetry to explain changes, not as the ranked result. Check all published
proofs against the pinned verifier and canonical digests. Do not change the
security profile, challenge manifests, judge, scoring code, or reference outputs
in a candidate submission. The capture script refreshes the prover's derived
CUDA manifests after source edits; do not edit them by hand. Challenge
maintainers keep judge changes separate from
candidate patches; any semantic contract change needs a reviewed new epoch
with its tests and reference data updated.

A participant opens a PR against the challenge repository with the captured
patch and completed notes. Its body should explain changed CUDA paths,
bottleneck, mechanism, before/after public time and memory, exact timing
scope, regressions, verification, tradeoffs, model/harness attribution, and
Discussion links. A PR is reviewable research; the current intake separately
accepts a fork URL plus immutable commit SHA and does not trigger on PR open.
Only a signed rank receipt is a leaderboard result. `spec/SUBMISSIONS.md`
defines the complete submission format and sequence.

The public CPI inputs and retained reference proofs live in `data/` using Git
LFS. Temporary generated proofs, logs, caches, private holdouts, and API
credentials belong outside Git. Never print or commit `STWO_PIE_API_KEY` or its
file contents.
