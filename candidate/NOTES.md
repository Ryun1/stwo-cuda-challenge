# Candidate notes

Candidate: remove a per-executed-instruction aggregation from the Cairo CUDA
allocation-geometry planner.

**No ranked result is claimed, and no before/after measurement from my own run
is available.** I have no NVIDIA GPU on this machine (macOS/arm64; no `nvcc`, no
CUDA runtime, no `zig build` of the CUDA products). Every number below is either
(a) read from this repository's own retained H200 report, and attributed as
such, or (b) explicitly labelled *unrun*. The prediction section states what an
operator must measure before this is believed.

## Bottleneck and mechanism

The `h200-v1` scored quantity is adapted-input-to-publication wall time. In the
repository's retained H200 run (`data/reports/h200-direct-2026-10-02.json`,
direct/unranked/unsandboxed), **ingress is ~76% of whole-command time** for the
six public PIE cases, and two ingress stages dominate:

| case | CPI MB | steps | `source_s` | `static_s` | proof stage `s` | whole `s` | peak GB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `15581148_15581148` | 359.5 | 18.81 M | 1.569 | 2.298 | 1.173 | 6.90 | 84.6 |
| `15582797_15582797` | 389.3 | 20.85 M | 1.666 | 2.594 | 1.283 | 7.63 | 90.5 |
| `15603744_15603744` | 424.1 | 22.22 M | 1.751 | 2.610 | 1.224 | 7.50 | 89.7 |
| `15590913_15590913` | 423.4 | 22.67 M | 1.762 | 2.442 | 1.547 | 7.78 | 105.2 |
| `15591789_15591789` | 472.0 | 25.38 M | 1.957 | 2.759 | 1.675 | 8.58 | 116.3 |
| `15588777_15588780` | 631.9 | 33.68 M | 2.565 | 2.841 | 1.952 | 9.78 | 134.1 |

`source_ns` fits `source_s = 0.206 + 0.003715 · MB`, **R² = 0.9964**, i.e. a
~269 MB/s single-threaded linear pass. It is the one stage that scales with
input, and `compile_canonical_source` is entirely CPU/I/O — no NVRTC, no device
work (the scout trace confirms `CudaPlan.compile` is pure metadata).

### The redundancy

`canonical_geometry.resolve` sized the `verify_instruction` compact component
like this (pinned `canonical_geometry.zig:63-67`):

```zig
var keys = try cairo.witness.verify_instruction_inputs.gather(allocator, input);
defer keys.deinit();
break :blk std.math.cast(u32, keys.rows.len) orelse return error.GeometryOverflow;
```

`gather` (`src/frontends/cairo/witness/verify_instruction_inputs.zig:79-106`)
builds an `AutoHashMap(Tuple[7]u32, u32)` with **one insert per executed
instruction**, materializes a `rows` slice, `sortUnstable`s it by pc, and scans
it for conflicts. The planner then reads exactly one field — `keys.rows.len` —
and frees everything. `gather`'s only production caller is this line (the other
two callers are CPU conformance harnesses), so the rows are dead work on the
CUDA path. That is ~20–34 M wasted 28-limb decodes plus 28-byte-keyed hash
probes, plus a sort, per proof.

### The fix

`instructionTuple` is a **pure function of `pc`** over an immutable `input`
(it reads only `input.memory` and `pc`), and every tuple's first word *is* `pc`.
Therefore

- distinct pcs ⇒ distinct tuples, so `|tuples| >= |pcs|`;
- equal pc ⇒ equal tuple by purity, so `|tuples| <= |pcs|`;
- hence `gather().rows.len == ` the number of distinct executed pcs, exactly.

So the count is reproduced with a bitmap over executed pcs, which also lets the
per-instruction validation run **once per distinct pc** instead of once per
execution. Changed path (the only one):

- `src/integrations/cairo_cuda/canonical_geometry.zig`
  - `resolve`: calls `distinctInstructionKeys` instead of `gather()`.
  - new `distinctInstructionKeys`: bitmap of one bit per memory address, filled
    from `input.state_transitions.casm_states_by_opcode.states`.
  - new `validateInstructionAt`: the admission half of the pinned
    `instructionTuple`, which is module-private and must be mirrored. It
    reproduces the pinned checks exactly: pc bounds, `isEmpty()`, the
    `raw >> 30` tag split with small/f252 index bounds, and the `limbs[8..]`
    non-zero rejection. The packed limbs 0..7 are not decoded because they only
    feed the row body, never admission.

Behaviour is preserved on both axes: **every pc is still decoded** (on first
sight, in the pinned iteration order, so the same malformed input fails with the
same error), and the value returned is the same integer, so `padded_rows`,
`active_rows`, the arena plan, the proof transcript and the published proof
bytes are unchanged.

Note the pinned tuple packs limbs 0..7, so its rejection loop starts at index 8,
not at `tuple_word_count` (7); the mirror uses `packed_limbs = 8` deliberately.

### Predicted effect (unmeasured)

If `gather` accounts for most of the 67 ns/executed-instruction marginal cost
implied by the fit — `(2.565 − 1.569) s / (33.679 − 18.810) M steps = 67.0 ns` —
then replacing ~60 ns/instruction with a ~1–3 ns bitmap probe predicts
`source_ns` falling by roughly 50–85%. That would be ~0.9–1.3 s off the median
PIE (whole command ~7.7 s) and ~1.5–1.9 s off the four-block case (~9.8 s).
**These are predictions, not results.** See the falsifier below.

Device peak memory should be **unchanged**: no new device allocation. The bitmap
is host memory, one bit per address — 4.6 MB for the 36.9 M-address four-block
case — and it replaces a hash table plus a sorted row slice, so host RSS should
fall slightly. That keeps the latency track's per-case `M_i/M0_i <= 1.10` guard
comfortably, but that must be measured, not assumed.

## Falsifier — the cheapest experiment

The repository already ships the instrumentation; no new code is needed.

```bash
STWO_CAIRO_SOURCE_STAGE_PROFILE=1 <cairo-cuda prove ...>   # per-sub-stage source_ns
STWO_CAIRO_CUDA_PROFILE_PREPROCESSED=1 <cairo-cuda prove ...>  # static-phase split
```

`resolve` sits inside the `geometry_and_air` window
(`canonical_source.zig:167`, between the marks at 166 and 169).

- **Prediction holds** if `geometry_and_air` is a large share of `source_ns` and
  visibly shrinks after the patch, with `input_read`, `multiplicity_feeds` and
  `request_compile` roughly unchanged.
- **Hypothesis refuted** if `geometry_and_air` is already small and
  `source_ns` is dominated by `input_read` (the 2× SHA-256 + re-read in
  `canonical_input.read:33-34`) or `multiplicity_feeds`. In that case the right
  target is the duplicated whole-input hash/re-read or the feed compiler, and I
  am wrong about where the 67 ns/step lives.

The smallest falsifying case is the one-block `15581148_15581148` (359.5 MB,
18.81 M steps): one run of the profile above, baseline and patched.

## Evidence

Source commit `b2873365dc28ed4bc4b27de10e01ea0beeef7c93`.

**Done:**

- `python3 challenge.py check-data` — verified 10 challenge tasks, 60 data files.
- `python3 challenge.py setup`, `python3 challenge.py paths` — pinned checkout at
  `workspace/stwo-zig`, confirmed present.
- `python3 challenge.py capture` — `CUDA product closure verified: 9 ordinary
  sources classified, 6 authority sources admitted, 8 resident candidates, 1
  quarantined/deferred, 340 copied AOT entries excluded, 48 Native AOT entry
  admitted, 271 legacy Cairo eval bodies … checked, 1 resident derivation
  verified, 147 active and 0 staged ABI symbols verified`, and
  `CUDA derivative manifests match source and pinned product policy`.
- `git apply --check` against the pristine `b2873365` worktree — applies cleanly.
- `zig ast-check src/integrations/cairo_cuda/canonical_geometry.zig` — parses.
- Patch is 1 file, +66/−5, inside the allowed `src/integrations/cairo_cuda/`.
  No other file in `workspace/stwo-zig` is modified (`git status --porcelain`).
- Public API surface used by the mirror (`EncodedMemoryValueId.raw`, `.isEmpty()`,
  `.index()`, `execution_tables.limb`, `MEMORY_VALUE_TABLE`, `BIG_LIMB_COUNT`) is
  all `pub`, confirmed by reading the definitions.

**Not run — stated plainly, no result implied:**

- `python3 challenge.py setup --build` and
  `python3 challenge.py benchmark --tier smoke --track balanced` — no H200 host
  available to me. **No smoke, qualify or rank run was performed.**
- The package's own Rust-oracle test, `canonical CUDA geometry matches
  independent Rust checkpoints` (in this same file, which checks `padded_rows`
  against `vectors/cairo/official/*.base_trace_checkpoint.json`). **It should be
  run before this patch is trusted** — it is the natural regression gate, since a
  wrong distinct count would change `padded_rows` and fail against the oracle.
- Proof verification (pinned `verify_cairo`), proof SHA-256 comparison, root and
  packed-tree digest comparison, whole-device NVML peak sampling. **Unrun.**
- Recursion and pipeline cases: untouched by this patch, but also **unrun**.

I could not compile the project locally at all, and that is a property of this
machine rather than of the patch. The repository needs a Zig with
`Step.Compile.addCSourceFile` (≤ 0.15). Zig 0.16 fails in the build system:

```
src/backends/cuda/build.zig:21:10: error: no field or member function named
'addCSourceFile' in 'Build.Step.Compile'
```

I reproduced that **identical** failure on the pristine `b2873365` baseline
worktree, so it is a pre-existing toolchain mismatch. Zig 0.15.1 was also tried
and cannot link its own runner on macOS 26 (`undefined symbol: _abort`,
`_clock_gettime`, … from `libSystem`). Hence no local compile or test evidence is
claimed, only syntax-level checking.

## Regressions

None observed, and none could have been measured. The change is output-neutral
by construction (§ mechanism: same integer, same error set, same iteration
order) and touches no security setting, fixture, verifier, judge or timer. The
one behavioural difference to watch is host RSS: the bitmap is
`address_count / 8` bytes, bounded above by 1/32 of the `address_to_id` table
that the input already holds, so it cannot dominate the capture.

## Tradeoffs and discussion

- Host memory: replaced a hash table over 28-byte keys plus a `Row` slice with a
  flat bitmap — expected to be smaller, not larger.
- Duplication: `validateInstructionAt` mirrors a pinned, module-private function.
  This is the real cost of the change. It is confined to one private helper, uses
  only the pinned public `execution_tables` primitives rather than re-deriving
  the limb layout, and names its pinned counterpart in the doc comment. The
  cleaner long-term fix belongs in `verify_instruction_inputs.zig` — a
  `distinctKeyCount` sibling of `gather` — but that module is **outside** the
  candidate edit surface (`benchmark.json` `editablePaths` lists only
  `src/backends/cuda`, `src/integrations/cairo_cuda`,
  `src/integrations/circuit_cuda`, `src/products/cairo_cuda`,
  `src/products/circuit_recursion_cuda`). A discussion thread proposes the
  upstream version.
- Blast radius: deliberately narrow. I considered and rejected overlapping the
  2.17 GB preprocessed artifact load in `executor/preprocessed_cache.zig` (the
  larger `static_ns`, ~2.5 s and roughly input-independent, which smells like
  disk + SHA-256 + H2D serialized in one thread). That needs pinned host
  staging plus stream events, and the pinned-symbol/closure gates make new
  exports risky. It is the better next target, not this one.

Hypothesis and falsifier posted as an Ideas thread:
https://github.com/teddyjfpender/stwo-cuda-challenge/discussions/2

Attribution: prepared with AI coding assistance (omp harness,
`openrouter/stealth/space-bunny-alpha`). Read-only `scout` subagents mapped the
static and source stages. All quantitative claims are re-derived from this
repository's committed `data/reports/h200-direct-2026-10-02.json` and
`data/reports/pie-workload-shapes.tsv`. No private fixtures, holdout
identifiers, credentials or proof blobs are included.

## Submission

Review PR: https://github.com/teddyjfpender/stwo-cuda-challenge/pull/3
Fork: https://github.com/Ryun1/stwo-cuda-challenge
Ideas thread: https://github.com/teddyjfpender/stwo-cuda-challenge/discussions/2

Immediate next step for an operator with a GPU: run the Rust-oracle geometry
test in the edited file, then `STWO_CAIRO_SOURCE_STAGE_PROFILE=1` on
`15581148_15581148` in both arms. If `geometry_and_air` does not move, reject
the hypothesis rather than the measurement.

Per `spec/ACTIVATION.md` the challenge is in staging: no live intake endpoint,
no self-hosted runner, and no signed rank receipt exists. A PR enters the
operator's daily queue; it does not start paid GPU work. Submission ID and
receipt: **none** — nothing was dispatched.