# Verification status

Updated 19 September 2026 after deploying revision
`fef4d8ae2d1ace9bf45ed08e183506f1df4eb45d`. Server-side AWS verification covers the new
live-search tool. ChatGPT verification of the refreshed 10-tool interface and a live search
is still pending because the Mac is locked. This file keeps direct MCP checks separate
from ChatGPT request cards.

## Current AWS release

- The deployed revision is `fef4d8ae2d1ace9bf45ed08e183506f1df4eb45d`. Direct MCP HTTP
  listed exactly 10 read-only tools; the full interface has 13 tools.
- `search_live_jobs("Technical Support Engineer", limit=10)` returned 10 reviewable jobs
  from 38 total and set `truncated=true`. Each configured live provider reported
  `cached=false` and `status=ok`:

  | Provider | Results | Fetched |
  |---|---:|---|
  | Himalayas | 4 | 2026-09-19 12:42:33-34 UTC |
  | Remotive | 5 | 2026-09-19 12:42:33-34 UTC |
  | Jobicy | 23 | 2026-09-19 12:42:33-34 UTC |
  | We Work Remotely | 6 | 2026-09-19 12:42:33-34 UTC |

- Using a returned live ID, `get_job_detail` and the three job-specific evidence tools
  (`score_fit`, `tailor_resume`, and `cover_letter_brief`) all completed successfully.
- A full SQLite dump digest was identical before and after the live search and follow-up
  calls, including jobs, profile, history, and source cache. The query caused no persistent
  database changes.
- Post-upgrade, the application, tunnel, watcher timer, and backup timer are all active
  and enabled; the tunnel `readyz` check is ready. The most recent backup reports success
  with exit status 0. SQLite integrity is `ok`, foreign-key failures are 0, and the job
  count remains 107. The previous runtime backup was retained; authentication and secrets
  were not changed.
- The feature CI run passed all five checks: Python 3.11, 3.12, and 3.13, dependency audit,
  and the Ubuntu installer check. See the
  [CI run](https://github.com/macrovise/career-search-mcp/actions/runs/35443489214).
  **89 local tests passed.**

Fresh retrieval is not a promise of complete provider inventory. The search is bounded by
provider availability and response limits; Scout and Adzuna remain disabled for the
external reasons below.

## ChatGPT status

The **earlier ChatGPT verification is historical** and covered the prior nine-tool
read-only interface. A fresh ChatGPT conversation returned real request and response
cards for six Career Search tools: `get_profile`, `search_saved_jobs`, and all four
evidence tools. The saved search used `Support Engineer`, limit 5, and returned five jobs
with `persisted=false` and `application_submitted=false`. The four evidence tools returned
real data; the synthetic `build_profile` fixture reported `saved=false`. The original
conversation rejected developer MCP calls, so a fresh conversation was required for those
checks.

That history does not verify `search_live_jobs` in ChatGPT. The new 10-tool list and a
live-search request from the ChatGPT app are still pending Mac access. The server-side AWS
HTTP check above does not count as ChatGPT verification.

Four Himalayas `search_jobs` calls also returned cards in the earlier fresh conversation.
They reported 154 UK and 41 worldwide Support Engineer matches, and 113 UK and 32
worldwide Technical Support Engineer matches. These were provider-reported totals, not
counts of unique retrieved jobs. Full-time did not establish permanent employment, and
salary, location, and legal eligibility still required evidence review.

No applications or external messages have been sent. No résumé or personal profile was
uploaded to a job source.

## Source status and external blockers

| Source | Current status |
|---|---|
| Himalayas | Live normalized results verified through the AWS adapter and the new live-search call. |
| Remotive | Live normalized results verified through the AWS adapter and the new live-search call. |
| Jobicy | Live normalized results verified through the AWS adapter and the new live-search call. |
| We Work Remotely | Live normalized results verified through the AWS adapter and the new live-search call. |
| Adzuna | Official GB adapter and mocked tests are in place; disabled until an app ID and key are configured. No authenticated live result is claimed. |
| Scout | Optional discovery scaffold remains disabled. Its provider rejected ChatGPT's OAuth callback because it is not on the callback allowlist; live schema, token, and search remain unverified. |

Source snapshots are bounded, not exhaustive. Provider filters can return irrelevant or
incomplete results. Review the title, full description, salary evidence, employment type,
and location eligibility. A live Himalayas MCP search with a £40k preference returned a
disclosed sub-threshold role, so salary evidence still needs local review.

## Earlier deployment and local validation

The initial AWS migration used revision `a8ad7ccc543ca8512014700479adf75bb26e8837`.
Its snapshot matched the source hash and passed integrity checks. It contained 107 jobs,
321 source identities, and 107 lifecycle events. The current revision preserves the
107-job database and is checked separately above.

Earlier direct HTTP and ChatGPT checks listed nine read-only tools. Earlier local
Streamable HTTP testing listed 11 tools before `search_saved_jobs` was added; the full
interface then had 12 tools. These counts describe prior revisions only. The current
revision has 10 read-only tools and 13 tools in the full interface.

The Docker Compose configuration validated, but Docker runtime execution remains
unverified because the local Docker daemon was unavailable. The AWS systemd deployment is
verified. Scheduled backups remain on the AWS disk; automated off-host backup storage is
not configured.
