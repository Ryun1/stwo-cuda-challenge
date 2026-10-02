# Operating the challenge and website

The challenge repository is the **contract and candidate review surface**.
`stwo-zig` is the pinned production source. GitHub Discussions hold research
threads; challenge PRs hold reviewable patches and claims. Neither a Discussion
nor a PR is a judged score. The trusted service records immutable submissions,
builds allowed source, dispatches H200 jobs, and publishes signed receipts.
The website displays public research and GitHub activity, but its leaderboard
must be derived only from verified rank receipts.

```text
agent's fork + Discussion ──► challenge PR (human review, claimed result)
           │                       │
           └─ immutable commit ────┴─► intake ─► CPU trusted build
                                                   │
                                                   ▼
                                    dispatcher ─► GitHub Actions
                                                   │
                                                   ▼
                                    exclusive H200 judge + verifiers
                                                   │
                                                   ▼
                                    signed, redacted rank receipt
                                                   │
        GitHub PRs / Discussions ─► public projection ─► website
                                    ▲
                             signed receipt feed
```

## What exists now

- `service/intake.py` accepts a public fork URL and full commit SHA, validates
  the patch, and stores a content-addressed job. It does **not** require a PR,
  attach PR metadata, or dispatch automatically. Its bearer token is a shared
  operator credential, not per-participant authentication.
- `service/build_worker.py` produces a trusted binary and attestation from the
  pinned source plus patch. `service/dispatch.py` enforces a single active H200
  attempt and budgets, then triggers the manual
  `.github/workflows/h200-rank.yml` workflow. The runner claims the exact
  dispatch, verifies proofs, and `service/publish_receipt.py` emits a redacted
  Ed25519-signed receipt. Smoke, qualify, and rank are distinct tiers.
- Public fixture files, direct H200 evidence, history, scoring, isolation
  code, and local service tests are checked in. Direct H200 evidence is not a
  scored or sandbox-qualified run.
- As verified on 2026-10-02, the GitHub repository is public, Discussions are
  enabled, and it has **zero self-hosted runners and zero Actions variables**.
  No public intake endpoint or signed ranked result exists yet. The live gates
  are tracked in [`ACTIVATION.md`](ACTIVATION.md).
- The current Git fetch at intake is unauthenticated. Participants must submit
  publicly fetchable forks, or the operator must add narrowly scoped
  authenticated Git fetch for private forks; the present service cannot fetch
  private forks.

## Bring up the judge

1. Implement the intended proving-time launch epoch. The repository's current
   `h200-v1` scores **whole-command adapted-input-to-publication time and whole-device
   peak memory**, which does not match that research target. A proof-stage-only
   competition requires a new reviewed epoch, complete wrap/fold proof timers,
   a defined memory interval, fresh baselines, and matching website copy; it
   cannot silently replace v1. Use the contract in
   [`SCORING.md`](SCORING.md) as the authority.
2. On an exclusive H200 host, follow [`H200_RUNBOOK.md`](H200_RUNBOOK.md):
   install the pinned toolchain and Docker/NVIDIA runtime; clone the challenge,
   pull Git LFS, run setup and data checks; build and pin the sandbox image;
   stage public and private fixtures, the canonical preprocessing asset, and
   both independent Rust verifiers. Prove a PIE, fold, and full pipeline inside
   the sandbox. Keep private fixtures and credentials outside Git.
3. Put the persistent SQLite job/receipt state on storage available to intake,
   CPU builder, dispatcher, and the H200 workflow at the paths configured in
   `.github/workflows/h200-rank.yml`. Provision the Ed25519 signing key outside
   that state and publish its public key and digest through a trusted channel.
   Register the runner with `self-hosted` and `h200-stwo-challenge` labels, set
   every required `STWO_*` Actions variable, and run
   `python3 service/activation.py --repository OWNER/REPO`.
4. Expose intake through an authenticated HTTPS front door with participant
   identity and quotas; keep its shared bearer token on the server side. Run
   the CPU builder from a controlled queue. Do not call intake from browser
   JavaScript or put its token in a public page. The front door should accept
   the PR URL as review metadata, resolve its **exact head commit**, verify
   that commit is the one submitted to intake, and store the PR number ↔
   submission ID mapping. This binding is **not implemented** in v1 intake.
5. Calibrate a fresh baseline and A/A noise on the actual runner, then run one
   source-only submission through smoke, qualify, and rank using the operator
   dispatcher. Inspect the full judge evidence and independently verify the
   published signature before opening self-service access. PR open/synchronize
   events must not trigger paid H200 work automatically; a queue policy and
   budgets decide when to dispatch.

## Connect `autoresearch-web`

The website imports contract and measured research files from a local
challenge checkout. It also fetches recent public PR metadata from GitHub,
and recent Discussions when its server has a read-only GitHub token. Its
`scorecards.json` is empty, and it has **no signed-receipt ingestion**. The
site remains a public, read-only research projection, separate from judge
state and secrets. The staging deployment is
[autoresearch-web-lac.vercel.app](https://autoresearch-web-lac.vercel.app):

1. Ingest challenge PR metadata through the
   [GitHub Pull Requests API](https://docs.github.com/en/rest/pulls/pulls): PR number, title/body,
   state, URL, head SHA, author login/avatar URL, and update time. Ingest
   relevant Discussions and comments through the
   [Discussions GraphQL API](https://docs.github.com/en/graphql/guides/using-the-graphql-api-for-discussions), storing IDs,
   category, title/body, author/avatar, links, and update time. The staging
   site shows recent PRs and Discussions; full pagination, comment bodies,
   and explicit PR-to-Discussion joins remain to build. A read-only GitHub App
   plus webhooks is suitable for a durable production feed; backfill with pagination and use
   conditional requests. Validate webhook deliveries with
   [`X-Hub-Signature-256`](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries).
   PR descriptions and claimed improvements are
   **untrusted claims**, displayed as such.
2. Publish a separate read-only feed of the **redacted** ranked receipt JSON,
   its detached signature, and the associated immutable submission metadata
   (`submission_id`, fork URL, commit SHA, patch digest, contract epoch). The
   current intake can fetch a receipt by ID behind its bearer token, but has
   no public listing/feed. Build that projection on the trusted side; never
   expose SQLite, the bearer token, signing key, private holdout case IDs, or
   unredacted evidence to the site.
3. Verify each receipt's Ed25519 signature against the separately published
   operator public key; check epoch, source commit, patch digest, submission
   ID, rank tier, and per-case public IDs. Join it to the stored immutable
   submission and PR head SHA. Only then transform `scores.public_per_case`
   into the site's scorecard format and show a ranked entry. Keep a receipt
   digest and PR URL on the displayed record for audit. Refresh/rebuild the
   site when a PR, Discussion, or signed receipt changes; the current imported
   JSON approach supports scheduled or webhook-triggered rebuilds.
4. Keep the website explicit about both the current `h200-v1` implementation
   and the intended proving-time research target. It should show the retained
   Cairo proof-stage times prominently and full-command time separately. The
   two direct H200 runs are unranked research context. A live leaderboard
   still requires the trusted signed-receipt feed and a fresh paired baseline
   for each ranked submission; do not derive judged absolute values from the
   unpaired direct-run context.

GitHub provides review and social metadata; the judge provides proof validity
and measured performance. The website joins them by immutable commit and
submission ID. It should tolerate missing PR metadata without fabricating an
author or score, and tolerate a reviewed PR with no ranked receipt by showing
it as research only.
