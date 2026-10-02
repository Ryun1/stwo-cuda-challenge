# H200 direct qualification, 2026-10-02

Two complete public-basket passes on one healthy NVIDIA H200 reproduced all
canonical proof and root hashes. Every Cairo proof passed its pinned Rust
verifier; every reported CUDA trial used the canonical 70-query, 26-bit PoW
profile with zero CPU fallbacks. The complete per-round measurements, binary
hashes, and PIE phase timings are in
[`h200-direct-2026-10-02.json`](h200-direct-2026-10-02.json). The
[`per-run TSV`](h200-direct-2026-10-02-runs.tsv) and
[`median TSV`](h200-direct-2026-10-02-summary.tsv) put measured proving phases
in their own columns; regenerate both with
`python3 scripts/export_h200_phases.py` from the repository root.
The pinned ReleaseFast baseline has a
[`build attestation`](h200-direct-2026-10-02-baseline-attestation.json), and a
separate clean zero-patch candidate worktree has its own
[`build attestation`](h200-direct-2026-10-02-candidate-empty-attestation.json).
Both worktrees were at the pinned source commit. The direct proof runs used the
baseline binaries; the candidate build has not been scored in a paired A/B run.

| Public case | Measured proving phase | Ingress | Whole command | Peak H200 memory |
| --- | ---: | ---: | ---: | ---: |
| PIE `15582797_15582797` | 1.28 s | 5.80 s | 7.63 s | 90.5 GB |
| PIE `15603744_15603744` | 1.22 s | 5.76 s | 7.50 s | 89.7 GB |
| PIE `15581148_15581148` | 1.17 s | 5.23 s | 6.90 s | 84.6 GB |
| PIE `15590913_15590913` | 1.55 s | 5.67 s | 7.78 s | 105.2 GB |
| PIE `15588777_15588780` | 1.95 s | 7.19 s | 9.78 s | 134.1 GB |
| PIE `15591789_15591789` | 1.68 s | 6.30 s | 8.58 s | 116.3 GB |
| Two-leaf recursive fold | unavailable | — | 2.90 s | 29.4 GB |
| Eight-distinct-PIE recursive fold | unavailable | — | 7.90 s | 29.4 GB |
| Two-leaf serial PIE-to-root pipeline | incomplete: Cairo leaves 0.93 s | — | 18.44 s | 69.5 GB |
| Two-leaf integrated-batch PIE-to-root pipeline | incomplete: Cairo leaves 0.77 s | — | 14.04 s | 41.3 GB |

The PIE proving phase is the backend's `proof_execute_and_decode_ns` counter,
converted to seconds. Despite that historical name, the timer ends at
`proof.finish`, **before** canonical verification, decoding, and publication;
it covers CUDA proof execution and finishing, not the entire command. Fold
`fold_stage_s` is 2.35 s for two leaves and 7.35 s for eight leaves, but it
also includes host construction and runtime lifecycle, so it is **not** a
proof-only value. The pipeline receipt contains Cairo leaf proof phases but
omits resident wrap/fold proof durations. The TSV leaves `proof_stage_s` empty
for both recursion and pipeline cases rather than substituting their whole
command time. Future H200 runs must retain each circuit `resident_ns` counter
and a trusted proof-stage interval before a complete proof-only comparison can
be ranked.

Whole-command time remains useful for measuring cold start, ingestion, and
publication overhead; it is the separate H200 v1 challenge metric. If the
production service supplies prepared GPU inputs, it should optimize and rank
an explicitly new proof-stage contract, while still reporting whole-command
time as an operational diagnostic. These two timing scopes must not be mixed
in a score or a historical comparison. Independent verification runs after
measurement. The standalone PIE Rust verifier took 0.051–0.069 seconds per
proof and is recorded separately. Peak memory is whole-device NVML usage
sampled every 10 ms. The
H200 reports 150.75 GB total device memory, so the largest public PIE stayed
below both capacity and the contract's 6 GB reserve. The two complete passes
took 90.1 and 92.8 seconds respectively, including command startup and
publication. For PIEs, ingress takes 5.2–7.2 seconds, versus 1.2–2.0 seconds
for proof execution and finishing. The staged static assets and source compilation
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
