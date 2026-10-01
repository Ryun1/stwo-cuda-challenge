# Task for an optimization agent

Improve CUDA proving of Starknet Cairo PIEs and their recursive aggregation on
one H200. Optimize the full path from an **already adapted** input to a
published, independently verified proof/root. Read `spec/WORKLOADS.md` and
`spec/SCORING.md` before editing; all cases and guards matter.

`./setup.sh` checks out the pinned prover in `workspace/stwo-zig`. Edit only
its allowed CUDA paths (listed in `benchmark.json`). Use the existing CPU,
Metal, and Rust reference implementations as sources of understanding, but do
not alter proof security, public outputs, verifier code, fixture selection,
measurement, or the challenge contract. Capture the patch with
`./scripts/capture-candidate.sh` and include a short `candidate/NOTES.md`
explaining the mechanism, expected benefit, tests, and known tradeoffs.
The capture script refreshes derived CUDA source/product manifests for kernel
edits and checks them against the pinned product policy. Do not edit those
manifests by hand; the upstream baseline closure remains immutable.

The fast loop is a small local compile/test and one public PIE or recursion
case. The expensive loop runs the whole H200 cohort only after the candidate
passes source policy and smoke verification. Correctness comes before speed:
standalone Cairo proofs need the pinned official Rust verifier and pipeline
leaves need the pinned production-registry Rust verifier; every recursive
root must verify and bind the expected contiguous leaves and output roots.

Look especially at fixed-asset upload and reuse, witness/lookup storage
lifetimes, host/device transfer, native CUDA kernels, batch scheduling,
wrap/fold circuit construction, and proof publication. Report measured phase
changes; do not infer end-to-end gains from kernel time alone.
