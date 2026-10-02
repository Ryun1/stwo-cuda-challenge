# H200 activation record

**Launch decision: staging, not open for ranked submissions (2026-10-02).**
The implemented `h200-v1` contract scores full-command time, while the intended
research target is GPU proving time. The website now foregrounds the six
retained Cairo proof-stage measurements and labels full-command measurements
separately. A proof-only competition requires a **new reviewed epoch** with
wrap, fold, and pipeline proof-stage timers, matching memory scope, and fresh
paired baselines. Do not launch the full-command v1 ranking as though it were
the proving-time challenge. Agents can use
the generated checkout, publish research in Discussions, and open review PRs
now. No PR or website number is a ranked result until the gates below are
qualified and the judge publishes a signed rank receipt. The operator should
keep the site's status at `staging` and should not advertise a live intake URL
or leaderboard while the runner, isolation, paired baseline, and receipt feed
are absent. The [source map](CODE_MAP.md) specifies exactly what agents edit.

This is the boundary between a tested challenge repository and a live ranked
service. The repository is currently private. No self-hosted H200 runner or
GitHub Actions judge variables are configured, so the manual H200 workflow
must not be dispatched yet. The concrete setup sequence is in
[`H200_RUNBOOK.md`](H200_RUNBOOK.md).

As checked on 2026-10-02, GitHub lists zero self-hosted runners for this
repository, and `service/activation.py` reports all ten H200 judge variables
missing. The funded Runpod session qualified the public proofs directly but
did not change these live-service gates.

| Gate | Current evidence | Required activation evidence |
| --- | --- | --- |
| Proof-stage scope | Six Cairo PIE proof stages retained at 1.17–1.95 s. Their 6.90–9.78 s full-command times include ingress. Wrap/fold proof-only timers are not retained. | Specify and implement a new proof-stage scoring epoch across all ten cases, add trustworthy wrap/fold/pipeline timers and memory interval, re-run baselines, and align judge and website before launch. |
| Contract and data | `check_data.py` verified all 60 public files after transfer to the healthy H200 pod; contract CI also passes. | Repeat the full hash check on the eventual trusted runner. |
| Independent verifiers | Both pinned Rust verifiers were built on Linux and accepted all relevant Cairo proofs in two direct H200 rounds; executable hashes are recorded in [`data/reports/`](../data/reports/README.md). | Build both verifiers from the pinned baseline on the trusted runner and run them inside the judge. |
| Public PIE output files | All six PIEs passed two direct H200 rounds with exact proof hashes and pinned Rust verification; see [`data/reports/`](../data/reports/README.md). | Repeat inside the trusted H200 judge to qualify isolation and ranked timing. |
| Eight-leaf CUDA fold | The two- and eight-leaf CUDA folds passed two direct H200 rounds, each with exact proof, outputs, and packed root hashes. Both two-leaf end-to-end pipeline modes also passed with Rust-verified Cairo leaves. | Repeat the fold and full pipeline inside the trusted H200 judge. |
| Private holdout | A separate 18-case manifest passes hash preflight locally; it is not in Git. | Mount private fixtures read-only on the judge; qualify its PIE, fold, and full-pipeline cases with the pinned verifiers. |
| Scoring | Three tracks, guards, ABBA scheduling, A/A dispersion, and bootstrap checks are covered by local scorer tests. Two unpaired baseline-only H200 rounds are recorded as diagnostics. | Capture a fresh baseline and three valid paired H200 rounds on the same exclusive host; inspect variance and device-memory samples. |
| Intake and dispatch | The intake, trusted builder, tiered receipts, one-active-job dispatcher, exact-run claim, persistent intake limit, conservative rolling GPU budget, and detached Ed25519 signing path pass local tests. Discussions are enabled on the private repository. | Configure the dedicated self-hosted runner, workflow variables, authentication, chosen request/GPU budgets, and queue operations. Provision an external operator key, publish its authenticated public half, and run one source-only submission through smoke, qualify, and rank. |
| Candidate isolation | The Docker/NVIDIA launcher stages case-only inputs and runtime assets and sanitizes the pipeline manifest. Hosted Linux [CPU probe #36923616450](https://github.com/teddyjfpender/stwo-cuda-challenge/actions/runs/36923616450) passed all eleven filesystem, network, PID, token, output, and forced-ENOSPC checks as UID 65532. A 2 GiB fixed-size per-case output filesystem and 64 MiB judge-side stdout cap are implemented; [`ISOLATION.md`](ISOLATION.md) defines the boundary. | Build the pinned CUDA image, then qualify GPU access, quota, and the launcher on the actual H200 runner with denied-access probes and valid PIE, fold, and pipeline proofs inside it. |

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
