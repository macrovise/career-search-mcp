# Verification status

Snapshot: 19 September 2026. This file separates server/API tests from ChatGPT verification.

## ChatGPT integration status

- Career Search MCP was created as a custom app. Settings showed **Connected** on
  19 September 2026 and listed nine read-only tools. It was explicitly selected in the
  original Job Integration Plugins conversation.
- Real `get_profile` and `search_saved_jobs` calls from that conversation were blocked by
  its runtime before returning data. The exact Career Search error is not yet available.
  Evidence-tool checks remain unverified. No Career Search ChatGPT call has succeeded.
- Himalayas Remote Jobs is connected in ChatGPT, and its unauthenticated MCP initialize,
  tools/list (41 tools), and direct endpoint search succeeded. Its selected ChatGPT call
  returned `FORBIDDEN: This conversation does not support developer MCPs`; no successful
  ChatGPT search is verified.
- Scout's endpoint returned 401 and OAuth discovery. Its provider rejected ChatGPT's
  callback because it was not on the callback allowlist. No token, live
  schema, or search was obtained.
- A fresh Developer Mode conversation is pending approval. Once approved, select
  Career Search MCP and/or Himalayas explicitly and retry a read-only tool call.

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

The local Python runtime is installed in a repository `.venv`. No public server or OAuth
identity provider is deployed. The Docker CLI is present but its daemon was unavailable,
so container execution is not verified. No applications or external messages were sent;
no résumé was supplied or uploaded.

The approved Career Search tunnel exists in the Personal Platform organization and target
ChatGPT workspace. Official Homebrew `tunnel-client` 0.0.14 is installed. The Restricted
runtime key is stored locally with filesystem mode `0600`; its path and value are omitted.
`tunnel-client doctor --profile career-search --explain` passed. After managed
`tunnel-client runtimes connect`, `tunnel-client runtimes status career-search --json`
reported `ready:true`, `healthy:true`, `process_running:true`, and
`runtime_state:ready`. The connected ChatGPT app lists nine read-only tools, but calls from
the original conversation have not returned data; a successful ChatGPT call is not verified.

The local MCP server is running at `127.0.0.1:8383` in read-only mode with nine tools. The
watcher completed a one-time run; the database contains 106 canonical listings. Continuous
watching is not running. The MCP server and watcher are separate processes and are not OS
supervised; the managed tunnel runtime does not supervise them. No scheduled database
backup is part of the documented Mac setup; use SQLite's backup API and test a restore.

## Completed local checks

- 74 automated tests passed on the Mac's Python 3.14 runtime. Tests cover official API/RSS
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
- The latest `career-watcher --once` run across all six target roles completed successfully.
  All four enabled source calls succeeded (including cached snapshots); the database now
  contains 106 canonical listings. It sent no messages or applications.
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
