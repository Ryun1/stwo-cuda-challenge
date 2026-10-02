# Candidate notes

Candidate: **vectorise the preprocessed-coefficient canonicality scan**, and
publish the measurements that redirect the rest of the ingress work.

**No ranked result is claimed and no H200 run was performed.** This machine is
macOS/arm64 with no NVIDIA GPU, no `nvcc`, and no CUDA runtime, so the prover
cannot be built or executed here. Every number below is labelled with the
machine and scope it was taken on. The optimisation is small relative to the
scored quantity; § *Negative results* is the more useful part of this
submission and is what I would act on next.

## Environment

| item | value |
| --- | --- |
| host | macOS (arm64), no NVIDIA GPU, no CUDA |
| project toolchain | Zig **0.15.2** (downloaded; this is the version the pinned source builds with) |
| benchmark/test runner | Zig **0.16.0** (Homebrew) |
| pinned source | `b2873365dc28ed4bc4b27de10e01ea0beeef7c93` |

Zig 0.15.2 cannot link its own test runner on macOS 26 (`undefined symbol:
_bzero`, `_clock_gettime`, … from `libSystem`), so I could not *run* 0.15.2
tests. I could **type-check** with it via `zig build-obj`, which skips the link
step. That distinction matters and is the reason the previous head shipped a
non-compiling patch: `zig ast-check` only parses, and does not resolve a
`usize` against a `u32` across a module boundary.

## Changed path

One file, inside an allowed `benchmark.json` `editablePaths` directory:

- `src/integrations/cairo_cuda/executor/preprocessed_cache.zig`

`load()` validated every coefficient of every column with a per-word scan whose
body could exit:

```zig
for (values) |value| {
    if (value >= 0x7fff_ffff)
        return error.NonCanonicalPreprocessedCoefficient;
}
```

The data-dependent early return is exactly what stops LLVM from widening the
loop: there is no fixed trip count free of an early exit, so the column
streams one `u32` per iteration. The fix folds a branch-free maximum over
`@Vector(8, u32)` lanes and tests once at the end.

The predicate is unchanged. `some value >= 0x7fff_ffff` holds **iff**
`max(values) >= 0x7fff_ffff`, so the same column raises the same
`error.NonCanonicalPreprocessedCoefficient` at the same point — after the
column is read, before `canonicalizeSimdCoefficientBlocks` and before the
upload. No coefficient value is altered, so the uploaded words, the device
arena, the FRI transcript and the published proof bytes are all identical.

The vector load is written as
`@as(*const [lane_count]u32, @ptrCast(values.ptr + index)).*` rather than the
more usual `values[i..][0..8].*`. The latter only coerces to a vector when the
bound is a **literal**; with a named `const lane_count` it fails to compile on
both 0.15.2 and 0.16.0 with `expected number, found '[8]u32'`. That cost me one
build cycle and would have shipped a broken patch had I not compiled.

## Measurement (host microbenchmark, **not** the scored metric)

`STWO_CAIRO_CUDA_PROFILE_PREPROCESSED=1` already prints `validate_ns` for this
exact loop, so the operator can confirm or refute the stage share directly on
an H200. Locally I reproduced the loop over the real element count — the
measured STWZPPC artifact is 2,172,407,516 bytes / **543,101,879 `u32`**
(2.02 GiB) — with the shipped code verbatim, Zig `-O ReleaseFast`, best of 3:

| form | time | bandwidth | vs pinned |
| --- | ---: | ---: | ---: |
| pinned: scalar `for` + early return | 124.87 ms | 17.40 GB/s | 1.00x |
| branchless scalar max fold (no vector) | 125.71 ms | 17.28 GB/s | 0.99x |
| **`@Vector(8, u32)` max fold (shipped)** | **32.03 ms** | **67.83 GB/s** | **3.90x** |
| `@Vector(16, u32)` max fold | 29.25 ms | 74.27 GB/s | 4.27x |
| floor: streaming sum, no compare | 128.87 ms | 16.86 GB/s | 0.97x |

**Saving: 92.8 ms per `load()` call** (this stage runs once per proof).

Two things this table settles:

1. **Vectorisation is the whole mechanism.** Removing the early return alone
   changes nothing (0.99x) — the scalar loop is already at the single-core
   streaming limit. The 3.90x comes from the SIMD fold extracting memory-level
   parallelism, visible as 17.4 → 67.8 GB/s.
2. **16 lanes is not worth taking.** 4.27x vs 3.90x, ~3 ms, and 16-wide
   `pmaxud` is AVX-512-only while the judge may run a non-AVX-512 host. The
   patch stays at 8 lanes (AVX2), which is why it is the one form shipped.

### Timing scope — stated separately, as required

- **This measurement covers:** the host CPU canonicality scan only, on arm64.
- **It does not cover, and I did not measure:** the proof stage
  (`cairo_execute_finish`, 1.17–1.95 s on the retained H200 run), the full
  command (6.90–9.78 s), ingress (5.23–7.19 s), or device peak memory.
- **Expected H200 effect:** the loop is unchanged in work, so the saving scales
  with the host's scalar-vs-SIMD single-core streaming gap. On x86 that gap is
  real but smaller than on this machine, so **I expect well under 0.1 s** of
  the 2.18–3.00 s `static` stage — comfortably under 1% of whole-command time.
  I am not claiming a score-relevant win.

## Verification

Done here:

- **`zig build-obj` on Zig 0.15.2, the project's own toolchain**, over the
  helper forced into an exported entry point so it is genuinely semantically
  analysed rather than skipped as lazily-referenced: clean, 4392-byte object.
  This is the check the previous submission was missing.
- **Two tests pass.** One is added to `preprocessed_cache.zig`; it walks
  lengths `{1, 2, 7, 8, 9, 15, 16, 17, 64, 129}` so every lane and the scalar
  tail are exercised, and asserts that a column is accepted at `0x7fff_fffe`
  and rejected at **every** index for both `0x7fff_ffff` and `0x8000_0000`.
  The second is a differential test over 40 random columns at each length
  1..40, asserting the vectorised fold accepts/rejects **exactly** what the
  pinned scan does.
- `python3 challenge.py capture` — closure and ABI gates pass (9 ordinary
  sources, 6 authority sources, 147 active ABI symbols).
- `git apply --check` against a pristine `b2873365` worktree: applies cleanly.
- Patch is 1 file, +61/-4, inside `src/integrations/cairo_cuda/`. No other
  file in `workspace/stwo-zig` is modified.

Not run — no result implied:

- `setup --build`, `benchmark --tier smoke|qualify|rank`: **no H200 host.**
- Pinned Rust `verify_cairo` / `verify_cairo_ex`, proof SHA-256, root and
  packed-tree digests, NVML peak sampling. **Unrun.**
- The recursion and pipeline cases. Untouched by this patch, also unrun.

## Negative results — please read these before optimising ingress

These are the measurements I would most like acted on. Three of the four
plausible "obvious" wins are dead ends, and I can say why with numbers.

1. **"Speed up the hashing" is a dead end on x86.** Zig 0.15.2's
   `std/crypto/sha2.zig:240` gates an `asm volatile` implementation on
   `builtin.cpu.hasAll(.x86, &.{ .sha, .avx2 })` — a real SHA-NI path. The H200
   host satisfies it, so admission hashing is already hardware-accelerated. A
   hand-written SHA-NI version would be redundant. (Zig 0.16.0 dropped this
   path — relevant only if the prover is ever rebuilt on 0.16.)
2. **Measured SHA-256 throughput: 954 MiB/s** over the six real public
   `.cpi` files (2700.3 MiB, 2034 ms one-shot, 2022 ms at 64 KiB chunks). My
   first run appeared to show 64 KiB chunking was 2.4x slower than one-shot;
   that was a bug in my own timing window, not a real effect. Chunk size makes
   no measurable difference.
3. **`canonical_input.zig:33-34` really does hash the whole PIE twice** —
   `sha(bytes)` over the owned buffer, then `fileSha(path)` which re-opens and
   re-reads the same 359–632 MB to detect a TOCTOU swap. That is a genuine
   redundancy worth 0.1–0.2 s per case on H200. **I deliberately did not change
   it.** The only semantics-preserving fix is to run the two independent hashes
   concurrently, which adds a thread to a security admission path I cannot run
   or compile in situ; and deleting the re-read would remove a deliberate
   check. I would rather propose it in a Discussion than ship it blind. The
   cleanest real fix is upstream in `cairo.adapter.input`: hash the bytes you
   own, once, and compare that to the pinned authority — that module is
   outside the candidate edit surface.
4. **The `static` stage is not the validation loop.** It is 2.18–3.00 s of the
   5.23–7.19 s ingress and looks like the obvious target, but the loop I
   optimised is only ~0.12 s of it locally. The rest is reading 2.17 GB,
   transposing it, and uploading 2.17 GB. **There is no pinned host memory
   anywhere in `src/backends/cuda`** — `context.zig` `upload`/`uploadSlice`
   hand raw pageable pointers to `cudaMemcpyAsync`, so all of that crosses PCIe
   through the driver's bounce buffer. That, and reusing the already-existing
   `DeviceImage` capture/restore for the second and later proofs, are the
   larger levers; I have not measured either.

Two further leads from the recursion path, unmeasured, for whoever picks this
up: `air_aot.admitBound` re-normalises and re-hashes every AIR program and is
called three times per circuit proof with identical arguments
(`geometry.zig:46`, `resident_composition.zig:36`, and again inside
`admitBound`); and in integrated batch mode `main.zig:250-253` re-reads and
re-parses each leaf proof JSON it just wrote at `verified_sink.zig:44`. Both
would matter for `pipeline:two-leaf-*`, where 17.5 s of an 18.4 s command is
not Cairo proving.

## Regressions

None expected, and none observed. The change is output-neutral by construction:
same accepted/rejected set, same error, same raise point, same uploaded bytes.
It allocates nothing and adds no device work, so device peak memory is
untouched. It touches no security setting, fixture, verifier, judge, timer or
manifest. The residual risk is narrow and specific: a wrong lane count or a
missed scalar tail would silently accept a non-canonical coefficient — which is
why the added test asserts rejection at *every* index for lengths on both sides
of the 8-lane boundary, and why the differential test compares against the
pinned scan directly.

## Tradeoffs

- 8 lanes over 16: 3.90x instead of 4.27x, chosen for AVX2 portability.
- An explicit `@ptrCast` to `*[8]u32` instead of the idiomatic slice-to-vector
  coercion, because the idiomatic form silently requires a literal bound. This
  is slightly more verbose and worth a comment upstream.
- The helper is a new private function rather than a macro-style change at the
  call site, so the call site stays one line and the reasoning lives with the
  algorithm.

## Attribution

Prepared with AI coding assistance (omp harness,
`openrouter/stealth/space-bunny-alpha`). Read-only `scout` subagents mapped the
Cairo CUDA host path, the CUDA backend host layer, and the recursion/pipeline
path. All quantitative claims are either re-derived from this repository's
committed `data/reports/h200-direct-2026-10-02.json` and
`data/reports/pie-workload-shapes.tsv`, or measured locally with the method
and machine stated above. Zig 0.15.2 was downloaded to match the pinned source.
No private fixtures, holdout identifiers, credentials or proof blobs are
included.

Note on this supersession: `workspace/stwo-zig` also carried a local
uncommitted edit to `src/products/cairo_cuda/app.zig` (flipping
`STWO_CAIRO_CUDA_STATIC_IMAGE` to default-on for reusable sessions). That edit
belongs to a **separate, already-submitted candidate** on the fork —
`candidate/fixed-asset-reuse-batch`, PR #11 — not to this one. I reverted it
in my local workspace only, so that this candidate's captured patch contains
exactly one file and stays attributable. Nothing on the fork was modified and
PR #11 is unaffected. The two are independent: this candidate touches the
coefficient canonicality scan, that one the fixed-asset device image.

## Status and next gates

This is **unranked research**. The patch compiles under the project's own
Zig 0.15.2 and the added tests pass, but **the projected speedup is unmeasured
on the target**, and I do not expect it to be score-relevant on its own.

Ordered next evidence gates:

1. `STWO_CAIRO_CUDA_PROFILE_PREPROCESSED=1` on `15581148_15581148`. Read
   `validate_ns` inside `static_ns`. If `validate_ns` is already near zero, this
   patch is worthless on H200 and the negative results above are the real
   finding.
2. `python3 challenge.py setup --build`, then
   `python3 challenge.py benchmark --tier smoke --track balanced`.
3. `--tier qualify` across the full basket, then `--tier rank` for paired
   rounds. Report proof stage and full command separately, never merged.

Per `spec/ACTIVATION.md` the challenge is in staging: no live intake endpoint,
no self-hosted runner, no signed rank receipt. A PR enters the operator's daily
queue and does not start paid GPU work. Submission ID and receipt: **none —
nothing was dispatched.** Only a signed rank receipt is a leaderboard result.
