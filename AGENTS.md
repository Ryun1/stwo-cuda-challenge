# Agent instructions

Read `TASK.md`, `spec/WORKLOADS.md`, and `spec/SCORING.md` before changing code.
The performance target is the full CUDA proving path on H200 for every fixed
case. Edit only the pinned prover source in `workspace/stwo-zig` under the
`editablePaths` in `benchmark.json`. Capture changes into
`candidate/changes.patch` with `scripts/capture-candidate.sh`; include an
explanation and measured results in `candidate/NOTES.md`.

Keep short iteration loops: compile and test the touched CUDA layer first,
then one public H200 smoke case, then the complete qualification basket.
Measure external process time and whole-device memory; use backend phase
telemetry to explain changes, not as the ranked result. Check all published
proofs against the pinned verifier and canonical digests. Do not change the
security profile, manifests, judge, scoring code, or reference outputs in a
candidate submission. Propose contract changes in a separate reviewed PR.

Large CPI inputs, generated proofs, logs, caches, and API credentials belong
outside Git. Never print or commit `STWO_PIE_API_KEY` or its file contents.
