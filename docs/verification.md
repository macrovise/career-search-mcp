# Verification status

Updated 19 September 2026 after deploying revision
`baf2013293169b6196323b2de50ac8b1103316c3`. Server-side AWS verification covers the new
live-search tool and the role-title relevance fix. ChatGPT Settings lists the refreshed
10-tool interface, and the final ChatGPT live-search check passed at 13:35 UTC. This file
keeps direct MCP checks, advertised metadata, and actual ChatGPT calls separate.

## Current AWS release

- The deployed revision is `baf2013293169b6196323b2de50ac8b1103316c3`. Direct MCP HTTP
  listed exactly 10 read-only tools; the full interface has 13 tools.
- `search_live_jobs("Technical Support Engineer", limit=10)` returned four reviewable jobs
  from four total and set `truncated=false`. Each configured live provider reported
  `cached=false` and `status=ok`:

  | Provider | Retrieved | Query matches | Filtered | Fetched |
  |---|---:|---:|---:|---|
  | Himalayas | 4 | 3 | 1 | 2026-09-19 13:35:07 UTC |
  | Remotive | 17 | 0 | 17 | 2026-09-19 13:35:07 UTC |
  | Jobicy | 50 | 1 | 49 | 2026-09-19 13:35:07 UTC |
  | We Work Remotely | 27 | 0 | 27 | 2026-09-19 13:35:07 UTC |

- Returned titles were `Sr. Technical Support Engineer, Focused Services`,
  `Associate Linux Support Engineer`, `Software Support Engineer`, and
  `Software Engineer - L3 Support`.
  Every returned record included matching query evidence; unrelated description-only
  matches were removed before applying the result limit.

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
  [CI run](https://github.com/macrovise/career-search-mcp/actions/runs/35446157353).
  **106 local tests passed.**

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

At 13:17 UTC, Settings → Plugins → Career Search MCP → Refresh displayed ten READ
actions, including `search_live_jobs` marked READ / OPEN WORLD. The updated definition
survived a page reload. However, the new [Live Search Failure conversation](https://chatgpt.com/c/6aae8b6f-0bb4-83ed-846f-672266224969)
reported `TypeError: tools.mcp__Career_Search_MCP__search_live_jobs is not a function`
and an inventory count of zero for that action. A subsequent retry in the same conversation
successfully discovered and called `search_live_jobs` at 13:30:20 UTC: five jobs from 37
total, with all four sources reporting `status=ok` and `cached=false`. The actual request
and response card was inspected in Safari. `get_job_detail` and `score_fit` also reported
success with a returned live ID. Thus the earlier discovery failure is no longer a blocker.

That first successful call exposed an unrelated SEO/ASO Manager result. The current
revision fixes the overly broad description-only matching and passed the direct AWS
acceptance above. The post-fix ChatGPT call at **13:35:31 UTC** returned all four relevant
jobs from four total (`limit=5`, `persisted=false`, `application_submitted=false`). All
four providers reported fresh requests, with the same retrieved/accepted counts as the
AWS check above. The result included the four support-engineering titles listed above
and no SEO/ASO Manager. ChatGPT then successfully called `get_job_detail` and `score_fit`
for the returned Palo Alto Networks live ID. The completed response and tool-call controls
were inspected in Safari; the conversation is linked above. Live IDs are temporary and
are not stable links to reuse later. An independent AWS detail read resolved the exact
live ID returned by ChatGPT to the same title and a 13:35:31 UTC source snapshot,
confirming that the conversation used a newly fetched server result.

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
