# Standalone PIE proof outputs

These six JSON files are the exact expected outputs for the six scored public
PIE proving cases. The original H200 sweep retained their SHA-256 digests but
not its raw JSON files. We reproduced the proofs from the same pinned source
commit (`b2873365dc28ed4bc4b27de10e01ea0beeef7c93`) on the Metal product.
Every reproduced file matched its previously recorded H200 digest byte-for-byte
and was accepted by the pinned official Rust `verify_cairo` adapter
(`stwo-cairo@82f21252`, `stwo@7b211edd`, Blake2s JSON transport).

The inputs, full digests, sizes, and task mappings are in
[`catalog.json`](../../catalog.json). The local reproduction used Zig 0.15.2,
`ReleaseFast`, canonical preprocessing, and `--verify`. Compact polynomial
storage was enabled for three dense inputs to fit this 64 GiB Mac; it did not
change their proof bytes. These are reference outputs, not H200 timing data.
The judge still produces and verifies fresh proofs on H200.
