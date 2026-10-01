# Scoring contract: H200 v1

The judge evaluates one submitted source tree on the frozen PIE, recursion,
and pipeline cases. Correctness, security, source policy, and physical memory
admission are hard gates. A failure on **any required case** emits no ranked
score in any track. The candidate cannot alter the manifest, verifier,
hardware telemetry, score computation, or baseline.

## Measured quantities

For each case `i`, `T_i` is the judge's monotonic wall time from an already
adapted input being presented to the candidate until the complete proof or
recursive root is published and the candidate process exits. It includes
candidate setup, loading, uploads, proving, host verification, and
serialization. It excludes fixture download,
PIE generation, Rust adaptation, judge-side independent verification,
queueing, and the one-time source build. Those excluded stages are always
reported separately. In a batch case, no per-leaf reset or hidden warmup is
allowed outside the measured interval. Reusing data **within** the timed batch
is allowed.

`M_i` is the highest **whole-device** bytes used during that same interval on
an otherwise exclusive GPU. A judge-side NVML sampler records it; candidate
telemetry is diagnostic only. The sampler period and idle/start/end readings
are in the receipt. Sampling is a lower bound on a very short transient peak,
so the hard admission check also uses the exact resident allocation plan,
and the judged host reserves 6 GB beyond that plan. A device OOM fails.

The judge runs the pinned baseline and candidate in interleaved ABBA rounds on
the same host, using fresh processes for cold cases and explicit persistent
processes for batch cases. It records at least three valid paired rounds;
per-case `T_i/T0_i` and `M_i/M0_i` are medians of paired ratios. The judge
repeats an A/A calibration before ranking and suspends promotions if host
variance exceeds the epoch's threshold. Neither the historical H100 pipeline
receipt nor the H200 PIE CSV is a scoring denominator.

## Aggregation and rankings

The fixed case manifest assigns every case a family: `pie`, `recursion`, or
`pipeline`. Each family gets one third of the log-weight, split equally among
its cases. This prevents many easy PIEs from drowning out the wrap/fold/root
path. Let `w_i` be those weights and let

`R_T = exp(sum_i w_i ln(T_i/T0_i))`,
`R_M = exp(sum_i w_i ln(M_i/M0_i))`.

Higher is better, baseline = 1:

| Track | Score | Additional guard |
| --- | --- | --- |
| Latency | `1/R_T` | Each `M_i/M0_i <= 1.10`. |
| Memory | `1/R_M` | Each `T_i/T0_i <= 1.50` and `R_T <= 1.25`. |
| Balanced | `1/sqrt(R_T * R_M)` | Each `T_i/T0_i <= 1.50`, each `M_i/M0_i <= 1.50`, and `R_T <= 1.25`. |

Every case must also remain below the H200 plan admission ceiling and publish
a verified result. The balanced score is an equal-elasticity tradeoff; it is
not claimed to equal cloud dollars per proof. On fixed-price H200s, latency
controls rental cost unless lower memory enables concurrency or a cheaper GPU.
The full Pareto frontier of `(R_T, R_M)` is retained separately, including
valid points that win neither scalar leaderboard. Later hardware-specific
economic tracks may measure actual simultaneous throughput and price.

For example, a candidate that is 20% slower and uses half the memory has
`R_T=1.2`, `R_M=0.5`, so its balanced score is `1/sqrt(0.6)=1.291`; it is a
good memory/balanced result under the latency guards, but does not beat the
latency leaderboard. That gain is a **capacity hypothesis**, not evidence of
1.291× cheaper production proving: concurrent throughput and GPU prices must
be measured separately. A candidate that halves time while using 11% more
memory is barred from the latency track by its 10% per-case memory guard, but
may enter balanced if every PIE remains physically admissible.

A new score must beat the current track leader by at least 1% **and** exceed
the paired A/A noise band. The runner records baseline A0/A1 dispersion in
each ABBA round. The promotion threshold against baseline is the larger of
1% or twice the median absolute A/A log dispersion (converted back to a
ratio). A deterministic 2,000-resample bootstrap over paired rounds recomputes
the same per-case median ratios and family-weighted score on each draw. It
produces 95% score intervals; the lower bound must clear that threshold. For an
existing leader, compare against a fresh leader run on the same host using
the same rule. Every per-case ratio is published; a median-only lucky run is
insufficient.

## Proof and work gates

Each Cairo proof is checked by the pinned official Rust verifier. The trusted
judge checks the input digest, public statement, canonical security parameters,
GPU-resident verdict, and absence of CPU proving fallback. This v1 epoch also
requires the canonical proof SHA-256 to match a pinned reference for every
case; all three qualified backends previously produced identical protocol
bytes. A recursive root is verified against the pinned recursion protocol and
expected leaf sequence, state-root continuity, outputs, and packed tree; its
proof bytes likewise match the pinned reference. The eight-leaf CPU root now
matches the pinned Rust reducer byte for byte; CUDA parity still requires an
H200 activation run before this basket can be ranked. A future epoch
may relax byte identity after a verifier can independently bind all expected
public statements. A candidate cannot substitute
precomputed proofs for hidden inputs: the judge chooses a private, hash-pinned
holdout after the source is fixed and validates statement binding.

Public tests are for development. Ranked testing requires a fresh source
checkout with only allowed paths applied, an isolated unprivileged process,
read-only fixtures, exclusive GPU, independent verifiers, and a judge-owned
clock. Build artifacts supplied by participants are fast-screening hints only;
ranked and promoted results rebuild from submitted source.
