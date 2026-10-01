# H200 activation record

This is the boundary between a tested challenge repository and a live ranked
service. The repository is currently private. No self-hosted H200 runner or
GitHub Actions judge variables are configured, so the manual H200 workflow
must not be dispatched yet. The concrete setup sequence is in
[`H200_RUNBOOK.md`](H200_RUNBOOK.md).

| Gate | Current evidence | Required activation evidence |
| --- | --- | --- |
| Contract and data | Local `check_data.py` checks 60 files; remote contract workflow [#36914842712](https://github.com/teddyjfpender/stwo-cuda-challenge/actions/runs/36914842712) passed the 60-file pointer check, including 36 LFS objects. | Repeat the full hash check after the runner obtains the public data. |
| Independent verifiers | The pinned standalone Rust verifier builds locally. Both retained production-registry H200 leaf proofs passed the pinned Rust `verify_cairo_ex` helper with the binary hashes in `data/README.md`. | Build both verifiers from the pinned baseline on the runner, record executable hashes, and run them in the judge. |
| Public PIE output files | Six proofs reproduced on pinned Metal match the previously recorded H200 digests byte-for-byte and pass pinned Rust verification; files are now under `data/outputs/pie/`. | Run the public PIE cases afresh on the H200 judge to qualify the end-to-end runner and timing. |
| Eight-leaf CUDA fold | Public inputs and a Rust-byte-identical CPU reference root are committed. | Run the CUDA `recursion:eight-distinct-pie-fold` case on H200 and require proof, outputs, and packed bytes to match the reference. |
| Private holdout | A separate 18-case manifest passes hash preflight locally; it is not in Git. | Mount private fixtures read-only on the judge; qualify its PIE, fold, and full-pipeline cases with the pinned verifiers. |
| Scoring | Three tracks, guards, ABBA scheduling, A/A dispersion, and bootstrap checks are covered by local scorer tests. | Capture a fresh baseline and three valid paired H200 rounds on the same exclusive host; inspect variance and device-memory samples. |
| Intake and dispatch | The intake, trusted builder, tiered receipts, one-active-job dispatcher, and detached Ed25519 signing path pass local tests. Discussions are enabled on the private repository. | Configure the dedicated self-hosted runner, workflow variables, authentication, rate and GPU-minute budgets, and queue operations. Provision an external operator key, publish its authenticated public half, and run one source-only submission through smoke, qualify, and rank. |
| Candidate isolation | The process environment excludes host tokens, and [`ISOLATION.md`](ISOLATION.md) defines the complete boundary. | Qualify a Linux/NVIDIA sandbox on the actual H200 runner with denied-access probes and valid PIE, fold, and pipeline proofs inside it. |

The operator builds assets with `./setup.sh --build`, hashes public fixtures
with `python3 scripts/check_data.py`, and uses `harness/run_arm.py --preflight`
against the private manifest before spending GPU time. The workflow's required
variables are listed in `.github/workflows/h200-rank.yml`; do not put private
paths, credentials, or holdout identifiers into this repository. The
`service/dispatch.py --dry-run` command checks a trusted build and tier gates
without reserving or launching a GPU job.
`python3 service/activation.py --repository OWNER/REPO` checks the live GitHub
runner and required variable names without displaying their values. A real
`service/dispatch.py` call performs this check before creating a workflow run.

Public release comes after these gates, with a reviewed contract epoch and a
fresh baseline score. Existing historical timings in the prover repository
are diagnostic evidence, not score denominators.
