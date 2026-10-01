# Research discussions

GitHub Discussions is enabled on the staging repository. The current GitHub
categories are **Ideas**, **Show and tell**, **Q&A**, **General**, and the
default announcements/polls categories. The repository provides category forms
for the first three:

| Category | Use it for | Form |
| --- | --- | --- |
| Ideas | One falsifiable profiling or optimization hypothesis. | `.github/DISCUSSION_TEMPLATE/ideas.yml` |
| Show and tell | Measured public results and reproductions, with a signed receipt for a ranked claim. | `.github/DISCUSSION_TEMPLATE/show-and-tell.yml` |
| Q&A | Setup, build, proof verification, and submission help. | `.github/DISCUSSION_TEMPLATE/q-a.yml` |
| General | Workload or scoring contract proposals; prefix the title `[Contract]`. | Free-form |

For a useful research thread, include the public case ID, exact source commit,
hardware, phase and memory measurements, a before/after comparison, and a
prediction that can be checked. Link unsuccessful experiments too. A local
timing is research evidence; only the independently verified, signed H200 rank
receipt is a leaderboard result. The public receipt must omit holdout case IDs.

Contract changes require a reviewed PR, a new manifest hash and baseline, and
a new epoch. A Discussion cannot silently change a live scoring contract.
Never post API keys, private fixture URLs, unpublished PIE bytes, proof blobs,
or runner logs containing secrets.
