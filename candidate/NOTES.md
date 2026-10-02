# Candidate notes — fixed-asset reuse for the resident batch pipeline

Second, independent candidate. Companion to PR #3
(`canonical_geometry.zig`); this one touches a **different file** and a
**different stage**, and the two patches can be applied together or separately.

**No H200 run of my own backs this, and no ranked result is claimed.** I have no
GPU and no Zig that compiles this repo's build system on this machine. The
numbers below are the challenge's own retained H200 report, attributed as such;
everything projected is labelled as a projection.

## Bottleneck and mechanism

`TASK.md` names "fixed-asset reuse" as a target. The fixed asset here is the
**2,172,407,516-byte (2.17 GB) `STWZPPC` preprocessed-coefficient artifact**,
loaded by `executor/preprocessed_cache.zig:132`. It is the dominant cost of
`static_ns` — the largest ingress stage in the retained report at **~2.53 s
median**, and nearly input-independent (2.298 s at 359 MB vs 2.841 s at 632 MB),
which is the signature of a fixed-size asset rather than per-input work.

A static receipt already exists so this artifact is loaded once per process.
It cannot be reused inside the batch pipeline, for two reasons that are visible
in the pinned source:

1. `app.zig:447-453` evicts the prepared Cairo arena after every leaf, so a
   circuit arena fits on the device — and evicts `resident_static` with it,
   because those coefficients lived inside the evicted arena.
2. The mechanism that *is* designed to survive that eviction,
   `preprocessed_cache.DeviceImage` ("A separately owned immutable device image
   survives arena eviction"), was gated behind an environment variable the judge
   never sets:

```zig
const use_device_image = external_runtime != null and (items.len > 1 or persistent != null) and
    image_setting != null and std.mem.eql(u8, image_setting.?, "1");
```

`harness/run_arm.py:38-40` builds the prover environment with
`STWO_CAIRO_CUDA_PREPROCESSED_COEFFICIENTS` / `_ARTIFACT_DIR` /
`_PREPROCESSED_VARIANT` but **not** `STWO_CAIRO_CUDA_STATIC_IMAGE`. So the
`pipeline:two-leaf-batch-integrated` case, which reaches
`proveBatchWithSinksUsingSession` (`circuit_recursion_cuda/main.zig:235`) and
therefore satisfies the first clause, loads the full 2.17 GB artifact **once per
Cairo proof** — twice per command.

Serial mode is worse structurally (3 processes, 5 CUDA contexts) but cannot be
fixed this way at all, because cross-process reuse is not possible.

### The change

One file, one hunk, +10/−3: default the device image on for exactly the
configuration where a later proof can actually reuse it.

```zig
const image_reusable = external_runtime != null and (items.len > 1 or persistent != null);
const image_disabled = image_setting != null and std.mem.eql(u8, image_setting.?, "0");
const use_device_image = image_reusable and !image_disabled;
```

`=1` keeps its old meaning, `=0` opts out, unset now means "on when reusable".

**Blast radius on the scored basket is exactly one case.** For the six
standalone PIE runs, `proveWithSink` passes `external_runtime = null`
(`app.zig:70`), so `image_reusable` is false and the behaviour is unchanged
byte-for-byte. The six recursion cases run `fold-tree` over pre-computed leaf
proofs and never load this artifact. Only the two-leaf integrated batch pipeline
changes.

### Predicted effect (unmeasured)

- Time: one 2.17 GB reload removed — read, SHA-256, M31 range check, SIMD
  transpose and pageable H2D — worth roughly the `preprocessed_load_ns` share of
  `static_ns`, i.e. ~2.2–2.4 s. `pipeline:two-leaf-batch-integrated` predicts
  **14.04 s → ~11.7 s (~−17%)**.
- Memory: +2.17 GB persistent device allocation, so peak predicts
  **41.3 GB → ~43.5 GB (+5.3%)**.

Under `spec/SCORING.md` (pipeline family = 1/3, split over 2 cases, so each
pipeline case carries weight 1/6) that is roughly:

| track | predicted | guard |
| --- | --- | --- |
| Latency | ×1.032 | `M_i/M0_i = 1.053 <= 1.10` ✅ |
| Memory | ×0.991 | `T_i/T0_i = 0.83 <= 1.50`, `R_T <= 1.25` ✅ |
| Balanced | ×1.012 | all ✅ |

**This is a latency-track candidate that slightly loses on memory, and ~1% is
right at the 1% promotion threshold.** It is worth far less than PR #3, which is
pure latency with no memory cost across six cases. Stated plainly so it is not
oversold: alone it is marginal; combined with #3 the memory cost is the only
downside across the whole basket.

## Falsifier — the cheapest experiment

Both signals already exist in the pinned code.

```bash
STWO_CAIRO_CUDA_PROFILE_PREPROCESSED=1 <leaf-wrap-batch ...>
```

`controller_bundle.zig:396-398` prints
`initial_upload_ns=… preprocessed_load_ns=… materialize_ns=… cached=… device_image_hit=…`
for every Cairo proof.

- **Confirmed** if leaf 2 reports `device_image_hit=1` and a near-zero
  `preprocessed_load_ns`, with the whole-command time falling by ~2.2 s.
- **Refuted** if leaf 2 reports `device_image_hit=0`. That would mean
  `deviceImageKey` (`preprocessed_cache.zig:83-107`) differs between the two
  leaves — the key covers path, `tree_ordinal`, `input_form`, `tree_size`,
  `column_logs`, `column_offsets`, total coefficient words and column
  identities. I expect all of these to be program-derived and therefore equal
  for two contiguous blocks of the same chain, **but I have not verified it.**
  If the keys differ, the image is evicted and rebuilt per leaf and this change
  is a **pure memory regression**: +2.17 GB peak, zero time saved. That is the
  single most likely way this PR is wrong, and it is cheap to check.

Smallest check: one `leaf-wrap-batch` run over the two public leaves with the
profile flag set.

## Evidence

Source commit `b2873365dc28ed4bc4b27de10e01ea0beeef7c93`.

**Performed by me:** `challenge.py check-data` (10 tasks, 60 files);
`challenge.py setup` / `paths`; `challenge.py capture` (CUDA product closure
verified; 147 active and 0 staged ABI symbols; derivative manifests match);
`git apply --check` against the pristine `b2873365` worktree — applies cleanly;
`zig ast-check src/products/cairo_cuda/app.zig`; `git status --porcelain`
confirms one modified file.

**Not performed — explicitly unrun:** `setup --build`; `benchmark --tier smoke
--track balanced`; `--tier qualify`; `--tier rank`; the preprocessed profile
above; pinned `verify_cairo`; proof SHA-256 comparison; root and packed-tree
digest comparison; NVML peak sampling.

**No compiler run exists for this patch.** The repo needs Zig with
`Step.Compile.addCSourceFile` (≤ 0.15). Zig 0.16 fails in the build system and I
reproduced that identical failure on the pristine baseline; Zig 0.15.1 and 0.15.2
both fail to link the build runner on this macOS release
(`undefined symbol: _abort`, `_malloc_size`, … from `libSystem`). So this change
is **syntax-checked only**. A PR reviewer with a working toolchain should run:

```
zig build --build-file src/integrations/cairo_cuda/build.zig test -Doptimize=ReleaseFast
```

The diff introduces no new types or coercions — it re-uses the
`std.mem.eql(u8, image_setting.?, …)` pattern already present on the line it
replaces — so type risk is low, but it is unverified.

## Regressions

- **Device memory rises ~2.17 GB** on the batch pipeline case, by design. This
  is the cost of the mechanism and is why the memory track gets slightly worse.
  It stays inside the latency track's 1.10 per-case guard and the balanced
  track's 1.50.
- **Behaviour on six PIE cases and two recursion cases: unchanged.** For PIEs,
  `external_runtime` is null so the image is never allocated.
- **Correctness guards are inherited, not weakened.** The device image's receipt
  is only promoted from `pending` to `admit` after a proof decodes and verifies
  (`app.zig:414-416`), so a failed proof cannot poison the cache;
  `DeviceImage.restore` re-binds the artifact identity to the request's
  commitment identity and re-validates before use; and `deviceImageKey` must
  match or the image is torn down. No security parameter, fixture, verifier,
  judge or timer is touched.
- **Main review risk:** this changes the meaning of an unset
  `STWO_CAIRO_CUDA_STATIC_IMAGE` from "off" to "on". That is a policy default,
  not a no-op refactor, and it is why an explicit opt-out exists. If the
  maintainers would rather not flip a default, the alternative is to set the
  variable in the harness — which is judge-side and therefore outside this
  candidate's edit surface.

## Tradeoffs and discussion

- Mechanism chosen because it is the pinned design's own answer to this
  problem, not a new invention: `DeviceImage` exists precisely to outlive arena
  eviction. The change only stops it being unreachable.
- Deliberately **not** attempted: pinning the host staging buffer in
  `preprocessed_cache.load` to speed up the H2D of the 2.17 GB artifact
  (~0.35 s on *every* Cairo proof, a broader but riskier win). It needs
  `cudaHostAlloc`/`cudaHostRegister` exposure, and
  `cuda_alloc_pinned_host_u32` exists in `authority/active/utils.cuh` but is not
  in `upstream_symbols.json` or `product_manifest.json`, so adding it perturbs
  the ABI closure the capture gate verifies. Not attempted blind.
- Not attempted: overlapping the artifact's disk read, hash, validate, transpose
  and upload, which are serialized per column in one thread.

Related: https://github.com/teddyjfpender/stwo-cuda-challenge/discussions/2

Attribution: AI coding assistant (omp harness,
`openrouter/stealth/space-bunny-alpha`), with a read-only `scout` subagent for
the pipeline path mapping. Baseline figures re-derived from this repository's
committed `data/reports/h200-direct-2026-10-02.json` and
`data/reports/pie-workload-shapes.tsv`. No private fixtures, holdout
identifiers, credentials or proof blobs.

## Submission

Review PR: https://github.com/teddyjfpender/stwo-cuda-challenge/pull/11
Fork commit: `fdb2d0e575688a96f6e9188d2df407ed0c5844e0`
Companion PR (different file, different stage):
https://github.com/teddyjfpender/stwo-cuda-challenge/pull/3
Fork: https://github.com/Ryun1/stwo-cuda-challenge

Per `spec/ACTIVATION.md` the challenge is in staging: no intake endpoint, no
self-hosted runner, no signed rank receipt. Submission ID and receipt:
**none** — nothing was dispatched, and no leaderboard result is claimed.