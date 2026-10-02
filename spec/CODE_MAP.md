# Where to change CUDA code

This repository stores the challenge contract, fixtures, and judge. The production
prover source is **not committed into this repository**. From the challenge root,
run `python3 challenge.py setup` once. It clones the pinned `stwo-zig` commit into
`./workspace/stwo-zig/` (singular **workspace**, relative to your clone); that
directory is ignored by Git, so it is absent in a fresh clone and on GitHub.
`python3 challenge.py paths` prints the absolute paths on your machine and says
whether setup has created the checkout. There is no `/workspaces/stwo-zig` path.

The pinned source is
[`b2873365`](https://github.com/teddyjfpender/stwo-zig/tree/b2873365dc28ed4bc4b27de10e01ea0beeef7c93).
Edit **only** these paths inside `workspace/stwo-zig`. The named files are starting
points, not a requirement to change all of them:

| Work | Files to inspect and change |
| --- | --- |
| Cairo proving lifecycle, batching, and output | [`src/products/cairo_cuda/app.zig`](https://github.com/teddyjfpender/stwo-zig/blob/b2873365dc28ed4bc4b27de10e01ea0beeef7c93/src/products/cairo_cuda/app.zig), `publication.zig`, `cli.zig` in the same directory. |
| Cairo witness, memory, trace, and FRI | `src/integrations/cairo_cuda/executor/proof_session.zig`, `resident_plan.zig`, `trace_commit.zig`, `pcs_fri_controller.zig`, and `ingress/writer_inputs.zig`. |
| Wrap and fold proving | `src/integrations/circuit_cuda/resident_prover.zig`, `resident_pipeline.zig`, `resident_memory_plan.zig`, and `native/circuit_grind.cu`. |
| Recursive pipeline CLI and proof publication | `src/products/circuit_recursion_cuda/main.zig` and `verified_sink.zig`. |
| Shared CUDA allocation, transfers, and scheduling | `src/backends/cuda/runtime/execution_plan.zig`, `device_admission.zig`, `execution_cache.zig`, and the kernels below `src/backends/cuda/`. |

The exact allowed directory list is machine-enforced by `benchmark.json`; the
five entries above are all within it. CPU, Metal, Rust, the challenge harness,
fixtures, and security settings are **reference material**, not candidate code.
After editing, run `python3 challenge.py capture`. It automatically includes
new files under the allowed directories and writes the source diff to
`candidate/changes.patch`. Commit that patch and `candidate/NOTES.md` in a PR
against **this challenge repository**. The judge applies the patch to a clean
copy of the pinned prover and builds it; it does not use your ignored workspace.

For a concrete first loop, inspect `workspace/stwo-zig/src/integrations/cairo_cuda/executor/proof_session.zig`, change one measured bottleneck in an allowed path, run a focused local check, then `python3 challenge.py capture`. On an H200 host, run `python3 challenge.py setup --build` and `python3 challenge.py benchmark --tier smoke --track balanced` before full qualification. See [SUBMISSIONS.md](SUBMISSIONS.md) for the complete PR and judge submission requirements.
