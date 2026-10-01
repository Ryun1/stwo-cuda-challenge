# Public challenge data

`inputs/` contains the adapted CPI files, output preimages, and verified leaf
objects needed by the public workloads. `outputs/` contains retained reference
proofs and root outputs. [`catalog.json`](catalog.json) maps each public task to
its required input files and exact expected output SHA-256 digests. The three
rankings (latency, memory, balanced) use the **same** tasks and data.

| Operation | Inputs | Expected outputs |
| --- | --- | --- |
| PIE proving (six scored cases) | `inputs/*.cpi` | Canonical H200 Cairo proof SHA-256 in `catalog.json` and `fixtures/public-v1.json`. The historical raw proof files were not retained. |
| PIE wrap (two-leaf CUDA reference) | `inputs/*.prover_input.cpi` and `inputs/*.preimage.hex.json` | `outputs/pie-wrap/two-leaf/*.cairo_proof.json` and `*.leaf_proof.json`. |
| PIE wrap (eight-leaf CPU reference) | `inputs/pie-wrap/eight-leaf/*.cpi` and `*.preimage.hex.json` | `outputs/pie-wrap/eight-leaf/*.leaf_proof.json`. These are CPU reference wrap proofs; they are **not** claimed to be official H200 Cairo JSON proofs. |
| Fold (two leaves) | `inputs/*.leaf.json` | `outputs/fold/two-leaf/root.proof`, `root_outputs.json`, `root_packed.json`. |
| Fold (eight continuous leaves) | `inputs/_tree8_proofs/*.leaf.json` | `outputs/fold/eight-leaf/root.proof`, `root_outputs.json`, `root_packed.json`. |
| Full two-leaf pipeline | Two CPI/preimage pairs in `inputs/` | The two-leaf wrap outputs plus the shared two-leaf root files above; serial and integrated batch must match the same bytes. |

The eight-leaf root was byte-matched to the pinned Rust reducer. The two-leaf
root and its wrap artifacts came from the retained H200 CUDA run. Its two Cairo
leaf proofs were accepted by the pinned Rust production-registry
`verify_cairo_ex` helper, with canonical binary digests
`a699160cbccf6869762d2473b349b64886858dc4dfec75869a012d2906cd9ff1`
and `7304ccf3636a7abcc6f1cfcf661af49f346fe7a2e537a276e65a43dc381e206a`.
The ordinary standalone PIE verifier uses a different serialization and does
not accept these leaf JSON files. Root proof
hashes are also pinned in `fixtures/public-v1.json`. These reference files are
for matching; the judge still regenerates proofs, independently verifies Cairo
proofs, and checks the canonical security profile.

Large CPI and proof files use Git LFS. Run `git lfs pull` after cloning and
`python3 scripts/check_data.py` to hash all 54 unique public files. The public
runner accepts this checkout directly with `--fixtures data/inputs`. A fixture
host can also populate missing inputs with `python3 scripts/fetch_public.py
--base HTTPS_BUNDLE_URL --out data/inputs`; that downloader checks the manifest
and every blob hash. The manifest keeps the original relative fixture names so
existing judge-owned stores and receipts remain compatible.
Both scored full-pipeline modes use these CPI and preimage files directly;
the runner does not need the original PIE ZIPs or a separate adaptation step.

The six standalone PIE proof hashes are valid output obligations, but their
raw historical proof JSON was not saved by the original H200 sweep. To fill
`outputs/pie/`, rerun those six inputs on a qualified H200 at the pinned source
and use `python3 scripts/collect_pie_proofs.py --arm-dir PATH_TO_H200_ARM
--verifier .cache/rust-official/release/stwo-cairo-official-verifier`.
The importer checks all six pinned hashes and independently verifies the
proofs before updating this catalog.
Do not substitute CPU-formatted Cairo JSON for an independently verified H200
proof. Until then, `catalog.json` sets `proof_file` to `null` for those cases.
