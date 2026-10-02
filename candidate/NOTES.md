# Candidate notes

Replace this template for each candidate. Capture `changes.patch` with
`python3 challenge.py capture` after editing allowed CUDA paths in the pinned
`workspace/stwo-zig` source; do not hand-edit the patch.

## Bottleneck and mechanism

State the observed bottleneck, changed CUDA paths, design, and predicted effect
on adapted-input-to-publication time and whole-device peak memory.

## Evidence

List public case IDs, hardware, source commit, exact timer boundaries, sample
counts, before/after time and memory, focused tests, Rust proof-verification
results, root/output matches, and regressions. Mark unrun checks explicitly.
Local timings are research evidence, not ranked results.

## Tradeoffs and discussion

Describe memory/speed or complexity tradeoffs and link relevant GitHub Ideas,
Show and tell, or Q&A threads. Include model/harness attribution and human
contributors. Do not include private fixtures, credentials, or proof blobs.

## Submission

Link the reviewable challenge PR. Once intake is live, add the immutable fork
commit SHA, returned submission ID, and any signed public receipt. A PR does
not automatically start the H200 judge; see `spec/SUBMISSIONS.md`.
