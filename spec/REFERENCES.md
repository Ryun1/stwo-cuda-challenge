# Challenge design and source references

The challenge fixes a source commit, editable CUDA paths, security parameters,
and public proof digests in `benchmark.json` and `fixtures/public-v1.json`.
Independent verification, judge-owned timing and memory measurements, and
private holdouts keep the score tied to valid work on unseen inputs. The
latency and memory tracks expose separate resource costs; the balanced track
uses their normalized product. Peak GPU memory is a capacity measure, not a
direct rental-price estimate.

The prover-specific implementation and protocol come from
[`stwo-zig`](https://github.com/teddyjfpender/stwo-zig):
[the H200 PIE study](https://github.com/teddyjfpender/stwo-zig/tree/main/vectors/reports/recursive-product-20260918/pie-scale-study-20261001)
and [the recursive CUDA pipeline receipts](https://github.com/teddyjfpender/stwo-zig/tree/main/vectors/reports/recursive-product-20260918/cuda-ingress-tree-scaling-h200-20261001).
The baseline source commit and every public input/proof digest are frozen in
`benchmark.json` and `fixtures/public-v1.json`.
