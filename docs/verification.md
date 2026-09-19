# Verification status

Snapshot: 19 September 2026. This file separates server/API tests from ChatGPT verification.

## Stage 1

- Himalayas MCP initialize and tools/list succeeded unauthenticated; 41 tools advertised.
  A generic UK technical-support search succeeded through its MCP endpoint. Its public
  JSON search API also returned Canonical worldwide support jobs and a Palo Alto UK role.
- Himalayas Remote Jobs was created and connected in ChatGPT through Safari. The settings
  page showed connection date 19 September 2026, endpoint, and discovered tools.
- An actual verification request in the existing Job Integration Plugins conversation
  reported the plugin was not exposed to that conversation. Therefore a successful
  ChatGPT search is **not verified**. Explicit plugin selection in a fresh/appropriate
  chat and a successful read-only tool call remain necessary.
- Scout's live MCP endpoint returned 401 and OAuth discovery. Public client registration
  was supported, but local callback authorization was rejected with HTTP 400 because
  the callback was not in Scout's allowlist. No token, tool schema, or search was obtained.
  No Scout account credentials/profile were transmitted. It still needs the supported
  ChatGPT connection flow and a separate provider-approved client for the watcher.
- Safari automation repeatedly timed out during subsequent setup. No Scout ChatGPT
  connection is claimed.
- On resumption, fresh Safari tabs and reloads briefly loaded ChatGPT, then returned
  a blank page. The original conversation loaded but its composer became unavailable
  before plugin selection. No additional successful ChatGPT tool call is claimed.

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

## Deployment

The local Python runtime is installed in a repository `.venv`. No public server, tunnel,
OAuth identity provider, hosting account, paid resource or always-on service is provisioned.
The Docker CLI is present but its daemon was unavailable; container execution is therefore
not verified. Local Python HTTP tests and container configuration checks are distinct.
No applications or external messages were sent. No résumé was supplied or uploaded.
The OpenAI Platform tunnel-settings page reached an existing Apple account sign-in
that requires the user to enter their Mac password. Tunnel entitlement and private
connectivity therefore remain unverified; no tunnel or credential was created.

See the task's final report for the final test count, commit hashes and live HTTP result.

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
- Ran the watcher once across all six target role names. All four enabled source calls
  succeeded (including cached snapshots), and it sent zero messages/submitted zero applications.
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

## Safari continuation

- OpenAI Platform sign-in completed. The Personal organization exposes tunnel management,
  including an existing unrelated OpenDesign tunnel. A separate Career Search MCP form
  was prepared for the same personal ChatGPT workspace; creation is awaiting confirmation.
- Installed the official `openai/tools/tunnel-client` Homebrew formula, version 0.0.14.
  No Career Search tunnel runtime has been launched or credential created.
- Created the Scout Job Search custom integration in ChatGPT and initiated its supported
  OAuth flow. Scout rejected ChatGPT's own generated callback with `invalid_request`:
  `redirect_uri is not on the allowlist of known MCP client callback URLs`.
  This is a provider-side callback allowlist blocker, not missing user credentials.
  No Scout search or completed connection is claimed; do not substitute an unauthorized
  callback or copy another client's token. The provider needs to support ChatGPT's current
  `https://chatgpt.com/connector/oauth/...` callback path. No message was sent to Scout.
- Explicitly selected Himalayas Remote Jobs in the existing ChatGPT conversation. The
  connector is now exposed and a real search was initiated. ChatGPT then reported that
  every `search_jobs` invocation was blocked by its runtime. The answer stream stalled
  before rendering the complete error; do not infer an HTTP status or provider cause.
  No successful ChatGPT search is verified.

## Approved tunnel creation

- Following explicit user approval, created a separate Career Search MCP tunnel in the
  Personal organization and existing ChatGPT workspace. Re-loaded the Platform list and
  verified the new record; the existing OpenDesign tunnel was unchanged.
- Prepared a private local tunnel profile using a file reference for the runtime key.
  The key file is empty, with private filesystem permissions, pending user credential
  creation/entry. No token is present in the repository or committed documentation.
- AWS was assessed as a future hosting option; no AWS resources were created.
- Re-ran the watcher for all six target roles after preparing the local deployment.
  All four enabled sources returned successful outcomes (with shared feed caches). The
  database contains 106 canonical records. No applications or messages were sent.
- Verified the running loopback MCP exposes nine read-only tools. Saved-job search and
  fit/resume/cover-letter evidence tools succeeded on real stored source records.
  This remains local verification; no Career Search ChatGPT call has succeeded yet.
