# Challenge design references

The [QSB challenge](https://github.com/Layr-Labs/quantum-safe-bitcoin-challenge)
provided the standalone `benchmark.json`, separate editable candidate paths,
`setup.sh`/`benchmark.sh` contract, manual self-hosted GPU dispatch, and
independent judge-owned measurement pattern. Its
[scoring specification](https://github.com/Layr-Labs/quantum-safe-bitcoin-challenge/blob/main/spec/SCORING.md)
is particularly clear that a candidate's own timing counters are not ranked
and that a fixed public test alone permits precomputation. This challenge
therefore hashes public inputs, keeps private holdouts, and uses an external
clock and verifier.

[sig.golf](https://github.com/Layr-Labs/sig.golf) contributes the pattern of
pinning the contract and verifier, separating candidate code from the judge,
and using [GitHub Discussions](https://github.com/Layr-Labs/sig.golf/discussions)
as a durable research channel. Its score is a product of two resources; our
balanced track uses a normalized time–memory product but retains separate
latency and memory tracks plus the Pareto record because GPU rental and
concurrency do not scale linearly with peak VRAM.

The prover-specific data and protocol come from
[`stwo-zig` PR #204](https://github.com/teddyjfpender/stwo-zig/pull/204):
[the H200 PIE study](https://github.com/teddyjfpender/stwo-zig/tree/main/vectors/reports/recursive-product-20260918/pie-scale-study-20261001)
and [the recursive CUDA pipeline receipts](https://github.com/teddyjfpender/stwo-zig/tree/main/vectors/reports/recursive-product-20260918/cuda-ingress-tree-scaling-h200-20261001).
The baseline source commit and every public input/proof digest are frozen in
`benchmark.json` and `fixtures/public-v1.json`.
