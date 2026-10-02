# Decision for the next proof-stage scoring epoch

The intended next ranking is **prepared request → encoded proof**, measured by
the judge, on one exclusive H200. This is a new epoch; `h200-v1` remains the
implemented adapted-input-to-publication contract and must not be relabeled.
The new clock excludes archive download, CPI adaptation, fixture file loading,
CUDA context creation, static preprocessing, independent verification, and
queueing. It includes input-dependent witness construction, transfers, all
CUDA and host proving work, recursive folds, GPU synchronization, and encoding
the proof bytes returned to the judge. This captures usable prover latency,
not merely the sum of GPU kernel durations.

The trusted judge must own the clock and the input boundary. Before the clock,
an uneditable adapter prepares the canonical request and retains its bytes;
the candidate process may initialize CUDA and static assets, but must not see
the request or private holdout paths. At T0 the judge supplies the request to
the resident candidate process. T1 is after explicit device synchronization
and the complete proof bytes have reached the judge. Candidate-reported
`proof_execute_and_decode_ns` and `resident_ns` remain diagnostics; editable
product code cannot supply a ranked timer. A modified candidate that performs
input-specific proving before T0 must be unable to access the request.

For a pipeline case, the clock starts with the first prepared CPI request and
ends when its single root proof is returned. All leaf proofs, wraps, folds,
inter-stage transfers, and encoding stay inside that one interval. The serial
and integrated modes remain distinct cases. For a fold-only case, wrapped
leaves are already prepared but withheld until T0. No per-leaf clock reset is
allowed. The independent Rust verification and exact protocol-byte checks
occur after T1.

The memory metric is the judge-sampled **whole-device peak** from T0 through
T1, including any resident cache retained between subproofs. Static pre-T0
allocations are also admitted by a separate device-capacity check; moving an
allocation before T0 cannot evade the H200 ceiling. The same 6 GB reserve and
exclusive-device rule remain in force. The new epoch needs its own paired
baseline and A/A calibration; historical command and self-reported phase
timings cannot be denominators.

Activation requires a frozen request protocol and adapter for all ten public
cases plus private holdouts; a judge-owned timer and NVML interval; denial of
pre-T0 input access; exact Cairo and recursion verification; three paired ABBA
rounds; and a candidate that deliberately lies about its internal timer to
prove ranking ignores that timer. The site and `benchmark.json` must then move
to the new epoch together. Until these tests pass on the H200, the challenge
remains staging and no proof-stage leaderboard can open.
