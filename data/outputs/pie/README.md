# Standalone PIE proof outputs

The original H200 sweep recorded canonical proof SHA-256 values for all six
scored PIEs but did not retain the raw proof JSON. Exact expected hashes are in
[`catalog.json`](../../catalog.json) and
[`fixtures/public-v1.json`](../../../fixtures/public-v1.json). The judge
regenerates and verifies each proof. After a qualified H200 rerun, use
`scripts/collect_pie_proofs.py` to check and import the raw reference files.
