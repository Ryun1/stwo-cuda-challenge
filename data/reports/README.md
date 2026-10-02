# H200 direct qualification, 2026-10-02

Two complete public-basket passes on one healthy NVIDIA H200 reproduced all
canonical proof and root hashes. Every Cairo proof passed its pinned Rust
verifier; every reported CUDA trial used the canonical 70-query, 26-bit PoW
profile with zero CPU fallbacks. The complete per-round measurements, binary
hashes, and PIE phase timings are in
[`h200-direct-2026-10-02.json`](h200-direct-2026-10-02.json).

| Public case | Median process time, 2 runs | Peak H200 memory | Median PIE ingress | Median PIE prove/decode |
| --- | ---: | ---: | ---: | ---: |
| PIE `15582797_15582797` | 7.63 s | 90.5 GB | 5.80 s | 1.28 s |
| PIE `15603744_15603744` | 7.50 s | 89.7 GB | 5.76 s | 1.22 s |
| PIE `15581148_15581148` | 6.90 s | 84.6 GB | 5.23 s | 1.17 s |
| PIE `15590913_15590913` | 7.78 s | 105.2 GB | 5.68 s | 1.55 s |
| PIE `15588777_15588780` | 9.78 s | 134.1 GB | 7.19 s | 1.95 s |
| PIE `15591789_15591789` | 8.58 s | 116.3 GB | 6.30 s | 1.68 s |
| Two-leaf recursive fold | 2.90 s | 29.4 GB | — | — |
| Eight-distinct-PIE recursive fold | 7.90 s | 29.4 GB | — | — |
| Two-leaf serial PIE-to-root pipeline | 18.44 s | 69.5 GB | — | — |
| Two-leaf integrated-batch PIE-to-root pipeline | 14.04 s | 41.3 GB | — | — |

Times cover the direct prover command; independent verification runs after
measurement. Peak memory is whole-device NVML usage sampled every 10 ms. The
H200 reports 150.75 GB total device memory, so the largest public PIE stayed
below both capacity and the contract's 6 GB reserve. The two complete passes
took 90.1 and 92.8 seconds respectively, including command startup and
publication. For PIEs, ingress takes 5.2–7.2 seconds, versus 1.2–2.0 seconds
for proof execution and decode. The staged static assets and source compilation
are the largest ingress components; their exact times are retained per case.

These runs were **direct, unranked, and unsandboxed**. They establish H200
functionality and reference equivalence, not a leaderboard score. Docker and
mounted output-quota isolation were not qualified on this Runpod pod; private
holdout, signed receipt, and paired A/B ranking remain activation
gates in [`spec/ACTIVATION.md`](../../spec/ACTIVATION.md). The first rented
Community Cloud H200 was discarded after a minimal CUDA context test returned
error 46 and NVML reported a GPU reset recovery action. No proof timings from
that faulty host are included here. The qualifying Secure Cloud H200 used
driver 580.178.04 and the pinned source commit recorded in the JSON report.
