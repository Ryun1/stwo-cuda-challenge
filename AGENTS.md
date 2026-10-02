# Agent instructions

Read `TASK.md`, `spec/WORKLOADS.md`, and `spec/SCORING.md` before changing code.
For the participant workflow and CLI, read `skills/stwo-cuda-challenge/SKILL.md`.
The performance target is the full CUDA proving path on H200 for every fixed
case. For a **candidate submission**, edit only the pinned prover source in
`workspace/stwo-zig` under the `editablePaths` in `benchmark.json`. Capture changes into
`candidate/changes.patch` with `scripts/capture-candidate.sh`; include an
explanation and measured results in `candidate/NOTES.md`.

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

The public CPI inputs and retained reference proofs live in `data/` using Git
LFS. Temporary generated proofs, logs, caches, private holdouts, and API
credentials belong outside Git. Never print or commit `STWO_PIE_API_KEY` or its
file contents.
