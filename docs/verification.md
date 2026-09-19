# Verification status

Snapshot: 19 September 2026. This file separates server/API tests from ChatGPT verification.

## ChatGPT integration status

- Career Search MCP is connected as a custom app with nine read-only tools. The
  original conversation rejected developer MCP calls, but a fresh Chat conversation
  successfully called the AWS service through the existing private tunnel.
- Actual ChatGPT request/response cards verified `get_profile` and
  `search_saved_jobs` (`Support Engineer`, limit 5, five returned records). The
  search response reported `persisted=false` and `application_submitted=false`.
- All four evidence tools also returned real data inside ChatGPT: `build_profile`
  used an explicitly synthetic fixture and returned `saved=false`; `score_fit`,
  `tailor_resume` and `cover_letter_brief` used an actual saved job. Every response
  identified `reasoning_owner=ChatGPT`. Writing briefs returned `saved=false` and
  `application_submitted=false`. No candidate profile was invented or persisted.
- Himalayas Remote Jobs also passed actual `search_jobs` calls inside the fresh
  ChatGPT conversation. Page-one searches for Support Engineer reported 154 UK
  matches and 41 worldwide matches; Technical Support Engineer reported 113 UK
  and 32 worldwide matches. These are provider-reported totals, not a count of
  unique retrieved jobs. Inputs used `type=full-time`, `salary_min=40000`,
  `currency=GBP`, `salary_required=false` and `sort=recent`.
- Himalayas returned Canonical Software Support Engineer and Software Engineer -
  L3 Support listings. Full-time does not establish permanent employment, and
  salary and legal location eligibility still require evidence review. The
  public endpoint is `https://mcp.himalayas.app/mcp`; its unauthenticated MCP
  initialize, tool listing and direct search also passed earlier.
- Scout's endpoint returned 401 and OAuth discovery. Its provider rejected ChatGPT's
  callback because it was not on the callback allowlist. No token, live
  schema, or search was obtained.

## Source adapters

| Source | Implementation / live state |
|---|---|
| Himalayas | Public JSON search API; live normalized records verified |
| Remotive | Official API; live normalized records verified |
| Jobicy | Official API; live normalized records verified |
| We Work Remotely | Public customer-support RSS; live normalized records verified |
| Adzuna | Official GB API adapter and mocked tests; live blocked by missing app ID/key |
| Scout | Opt-in MCP discovery scaffold; live schema/token/search not verified; disabled by default |

Source snapshots are bounded, not exhaustive. A provider may return irrelevant roles;
review the title, full evidence and eligibility. Salary filters are not trusted alone:
a live Himalayas MCP search with a £40k preference returned a disclosed sub-threshold
role, so deterministic local exclusions are required. Salary estimates and undisclosed
pay remain reviewable. Contract listings are excluded separately.

## Current deployment status

Career Search is deployed on Ubuntu 24.04 in AWS London using a `t3.small`,
encrypted retained 20 GiB gp3 disk and the existing private OpenAI tunnel. The
application revision is `a8ad7ccc543ca8512014700479adf75bb26e8837`. Inbound SSH is
restricted to the administrator's IP; no application or HTTP ports are public.
The MCP server and tunnel health listener bind only to loopback. Separate system
users and hardened systemd services run the application and tunnel. No AWS API
credentials or application IAM role are present on the server. The temporary
root CLI deployment session was signed out and its credential cache was empty.

The consistent migration snapshot matched the source hash and passed integrity
checks. Fresh discovery across all six target roles succeeded for Himalayas,
Remotive, Jobicy and We Work Remotely, producing 107 canonical jobs, 321 source
identities and 107 lifecycle events. All jobs remain `discovered`; no profile
record, application or external message was created.

A real MCP HTTP client listed exactly nine read-only tools and successfully called
`get_profile`, `search_saved_jobs` and all four evidence tools. Evidence responses
identify ChatGPT as the reasoning owner; the synthetic `build_profile` test returned
`saved=false`. These server checks are separate from the ChatGPT checks above.

The application, private tunnel, six-hour discovery timer and daily backup timer
are enabled and active. A real reboot changed the boot ID; both tunnel health
checks and MCP HTTP reads passed afterward. Database counts survived unchanged,
with SQLite integrity `ok`, zero foreign-key failures and zero orphan events.
The old Mac tunnel runtime is stopped.

Daily backups retain seven snapshots on the AWS disk. A current 107-job backup
was downloaded to the Mac and passed integrity checking. Scheduled backups are
not yet copied off-host automatically. The Docker daemon was unavailable locally;
container execution remains unverified, while the systemd deployment is verified.

## Automated checks and earlier local validation

- 79 automated tests passed on the Mac's Python 3.14 runtime. Tests cover official API/RSS
  adapters, opt-in Scout's mocked MCP contract, cross-source deduplication and provenance,
  concurrent ingestion, lifecycle/follow-up persistence, evidence-only reasoning tools,
  SSRF/redirect/response-size controls, and signed-token HTTP authentication.
- Ruff lint and formatting passed. `pip check` reported no broken requirements.
- Dependency audit reported no known vulnerabilities after updating pip; the unpublished
  application itself cannot be assessed through PyPI's dependency advisory service.
- Actual local Streamable HTTP MCP initialization and tool listing succeeded (11 tools).
  `search_jobs` returned 28 listings across all four enabled sources; 27 remained for review
  and one contract listing was excluded. Evidence tools succeeded for a returned job ID.
- Restarted the local server using the same database and repeated the HTTP workflow;
  source cache and records survived. This does not constitute ChatGPT verification.
- The earlier local `career-watcher --once` run across all six target roles completed successfully.
  All four enabled source calls succeeded (including cached snapshots); that local snapshot
  contained 106 canonical listings before migration. It sent no messages or applications.
- Compose configuration validated using the example environment. Docker runtime testing
  remains unavailable because the Docker daemon was not running.
- Added a read-only surface for clients with read/fetch access: `CAREER_READ_ONLY=true`
  removes all three mutating tool handlers. Tests prove they cannot be called and
  saved-job search leaves database contents unchanged. The four reasoning tools remain.
- An actual loopback Streamable HTTP smoke test listed nine read-only tools, searched
  a synthetic stored Technical Support Engineer fixture, and exercised all four
  evidence tools successfully. This is transport validation, not a live provider call
  or ChatGPT connection. The temporary server was stopped afterward.
- The complete interface now has 12 tools, including the new `search_saved_jobs`;
  the earlier live 11-tool test predates that addition.
- CI passed on Python 3.11, 3.12 and 3.13, including the dependency audit and an
  actual Ubuntu 24.04 installer, restricted-service HTTP and backup test. See the
  [deployed revision's CI run](https://github.com/macrovise/career-search-mcp/actions/runs/35438699831).
