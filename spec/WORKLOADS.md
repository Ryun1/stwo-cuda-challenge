# Workload contract

The challenge covers the CUDA **system**, not only isolated kernels. Cases
come from the hash-pinned `fixtures/public-v1.json` plus a private holdout with
the same shape categories. Every ranked case starts after SNOS PIE generation
and pinned Rust bootloader adaptation, at immutable `.cpi` bytes. The public
manifest records hashes, sizes, block spans, and source receipts; fixture
blobs are mounted outside Git under `STWO_FIXTURE_ROOT`.

The PIE family deliberately spans ordinary one-block and multi-block inputs,
high EC/Poseidon, bitwise, Pedersen, and a near-capacity one-block case. A
44.94M-step ten-block PIE that proved with only 2.91 GB of physical headroom
is a **diagnostic** outside the ranked basket. If a ranked case's exact plan exceeds the 6 GB reserve
on a particular H200, that host cannot rank this epoch. The historical H200
results are calibration evidence only. They are not frozen score denominators.
The catalogue study and provenance are in `stwo-zig` at
`vectors/reports/recursive-product-20260918/pie-scale-study-20261001/`.

Recursion cases take distinct circuit leaf proofs and perform
canonical `circuit_multiverifier` folds. The
public two-leaf case uses contiguous mainnet block ranges 15,627,902–904 and
15,627,905–907 from the committed `stwo-zig` manifest. The root must bind the
same ordered leaves and public outputs. The official H100 receipt is only
reference provenance; H200 baseline timings require fresh measurement.
The second public case folds eight different ten-block PIEs spanning blocks
15,578,420–499. Their ZIP headers join by block number and state root; their
adapted inputs, leaf proofs, and seven-fold root are hash-pinned in
`fixtures/tree8-provenance.json`. A synthetic repeated-leaf tree is permitted
only for smoke tests and cannot earn a score.
The eight-leaf root was produced by the pinned `main` CPU prover; its CUDA
byte-parity is a required H200 activation check, not a claimed measurement.

The pipeline family runs from already adapted contiguous PIE inputs to one
published recursive root, including Cairo proof publication, leaf wrapping,
and all folds. Both the serial multi-process path and the integrated resident
batch path are scored, so setup reuse matters without letting a batch skip
proof stages. The final applicative Starknet aggregate proof is outside this
epoch because that separate binding stage is not yet qualified in the pinned
pipeline. The contract will gain a new epoch when it is.

The judge runs the independent official Rust verifier on every Cairo proof.
For recursive proofs, this v1 judge requires byte equality to the pinned
reference proof and output/packed-tree digests, in addition to source input,
registry, and security checks. The exact-reference rule is a deliberately
stricter acceptance condition than generic proof validity; a later epoch can
admit other valid transcript bytes after it has a separate runtime circuit
verifier request and gate.
Any candidate that changes the statement, skips a proof stage, lowers FRI
security, or proves on CPU fails.

Large PIE CPI blobs and preprocessed assets must not be committed to this repo.
The fixture publisher writes a signed/content-addressed manifest and uploads
each blob once. The H200 worker fetches by digest to persistent local storage
before timing, hashes every file before use, and uses a read-only bind mount.
Private holdouts use different files from the public development set.
