# Local development, secure hosting and ChatGPT connection

## Do you need hosting?

ChatGPT needs a route to the running MCP server. That can be a server on a hosting
provider, or your Mac through OpenAI's private Secure MCP Tunnel if available for
your account. A local command alone is not a ChatGPT connection. With the Mac option,
it must stay powered on, awake and connected for searches and the watcher to run.
This repository provisions no hosting subscription, tunnel, identity tenant, paid resource
or persistent system service.

Start with local validation (README). For production, the supported public-server
configuration uses a persistent volume, HTTPS reverse proxy, and an external OAuth
provider. Do not expose local/no-auth mode via a generic public tunnel.

## Environment

Copy `.env.example` to `.env` locally; do not commit it. The server and watcher read it.

| Variable | Use |
|---|---|
| CAREER_AUTH_MODE | `oauth` default, or `local` for trusted loopback tests only |
| CAREER_READ_ONLY | `false` default. Set `true` to hide/reject all five writes: `search_jobs`, `save_profile`, `update_status`, `import_job_evidence`, and `mark_as_applied`; 13 read tools remain available |
| CAREER_PUBLIC_URL | HTTPS origin/base URL; token audience is this URL plus `/mcp` |
| OAUTH_ISSUER | Exact issuer in signed access token, including any trailing slash |
| OAUTH_JWKS_URL | HTTPS signing-key discovery endpoint |
| OAUTH_OWNER_SUBJECT | Exact immutable `sub` claim for the owner; rejects other users |
| MCP_HOST / MCP_PORT | `127.0.0.1` / `8383` defaults |
| CAREER_DB_PATH | `data/career.sqlite3`; Docker uses `/data/career.sqlite3` |
| CAREER_SOURCES | Comma-separated enabled source names |
| WATCH_INTERVAL_SECONDS | Defaults/minimum 21600 (six hours) |
| ADZUNA_APP_ID / ADZUNA_APP_KEY | Optional official Adzuna credentials, GB market |
| SCOUT_ACCESS_TOKEN | Optional provider-issued token for an approved independent client |
| SCOUT_DISCOVER_ARGUMENTS | JSON argument template matching the verified live Scout schema |

No Anthropic, OpenAI API, embedding, SMTP, scraping-service or LibreChat identity
credentials are needed by Career Search MCP. An OpenAI Secure MCP Tunnel, if chosen,
has its own separate credential requirements; those are not model API calls.

## Public OAuth deployment

1. Choose a single-host service with a persistent local disk and HTTPS. Ephemeral
   filesystem-only/serverless deployments will lose jobs and profiles and are unsuitable.
2. Configure an OAuth authorization server supporting authorization code + PKCE S256,
   discovery metadata and ChatGPT client registration (dynamic registration or a supported
   explicitly configured client). Restrict access to your account. Register the exact
   callback URL displayed in ChatGPT, not a guessed shared callback.
3. Configure RS256 access tokens with the exact issuer, audience
   `https://YOUR-HOST/mcp`, an expiration, immutable owner subject and `career:access` scope.
   Set the environment variables through the deployment secret manager.
4. Run `docker compose up -d --build` with a populated `.env`. Both containers share
   the `career-data` volume. Only the MCP loopback port is published. Put an HTTPS
   reverse proxy on that host in front of `127.0.0.1:8383`; permit Streamable HTTP and
   serve the `/.well-known/oauth-protected-resource/mcp` metadata route too.
5. Verify an unauthenticated `/mcp` request returns 401 and `WWW-Authenticate` points to
   resource metadata; verify the metadata resource is exactly the token audience.
   Test expired/wrong-audience/other-user tokens fail, then test an owner token succeeds.
6. Keep the disk encrypted and back it up consistently using the SQLite backup API.
   Test a restore before relying on it. Do not run two hosts against different copies.

The app is an OAuth resource server, not an OAuth account provider. Do not deploy a
fake bearer secret as if it were a complete ChatGPT OAuth flow. Local tests prove the
resource-server logic; provider consent/refresh and actual ChatGPT account linking
still require a real deployment test.

## Private Secure MCP Tunnel alternative

[OpenAI's Developer Mode documentation](https://developers.openai.com/api/docs/guides/developer-mode)
supports read and write MCP tools on ChatGPT Pro. Write actions require confirmation by
default. `CAREER_READ_ONLY=false` exposes all 18 tools; set it to `true` only when a
13-tool read-only surface is desired. This choice does not require a plan upgrade.
`search_live_jobs` remains non-persistent in either mode; `search_jobs` saves discoveries.

The existing Career Search tunnel and custom app are backed by the AWS London server.
The official tunnel client runs as a restricted systemd service, with its runtime key held
in a root-owned file and delivered through systemd credentials. The MCP service listens at
`127.0.0.1:8383`; no inbound public application port is open. The Mac tunnel runtime is
stopped.

Historical ChatGPT verification on 19 September covered the earlier nine-tool interface:
a fresh Chat conversation successfully called `get_profile`, `search_saved_jobs` and all
four evidence tools through AWS. That remains evidence for those six calls, not for the
new live-search tool. The historical AWS revision, `baf2013293169b6196323b2de50ac8b1103316c3`,
exposed 10 read-only tools and 13 tools in the full interface. Direct MCP HTTP verification
searched for `Technical Support Engineer` with a limit of 10, returned four reviewable jobs
from four total, then passed a live ID to `get_job_detail`, `score_fit`, `tailor_resume`,
and `cover_letter_brief`. The complete SQLite dump digest was unchanged before and after.
At that revision, ChatGPT Settings listed all ten tools after Refresh. Following an initial discovery failure,
a real ChatGPT live-search call and follow-up evidence reads succeeded. See
[verification status](verification.md) for the separate server and ChatGPT evidence.

On 20 September 2026, the existing AWS service was switched to `CAREER_READ_ONLY=false`.
Direct inventory verification confirmed 18 tools, including five write tools. The private
tunnel and loopback binding remain in place. ChatGPT connection refresh and actual idempotent
write/read-back verification passed in both replacement career agents. These checks do
not establish unattended scheduled write support or interactive card rendering.

Use the [AWS deployment guide](../deploy/aws/README.md) for the active hosted setup.
The following Mac instructions describe a local alternative; switching back requires
the documented cutover so only one tunnel and database remain authoritative.

### Tunnel and runtime prerequisites

- Create or select a tunnel in Platform Tunnels and associate it with the intended ChatGPT
  workspace so it appears in that app's Tunnel picker. This Mac already has an approved
  Career Search tunnel in the target workspace.
- The runtime principal and the person attaching the ChatGPT app need Tunnels Read + Use.
  Creating or editing a tunnel needs Tunnels Read + Manage.
- Use a **Restricted** runtime key with Tunnels Read + Use. It authenticates the tunnel
  runtime; it is not a ChatGPT credential and does not make model API calls. Reference it
  as `file:/path/to/restricted-runtime-key`; never put its value in shell history or the
  repository.
- The machine running `tunnel-client` needs outbound HTTPS to `api.openai.com:443` and
  local reachability to the MCP service. The MCP server does not need an inbound public port.

On macOS, OpenAI documents Homebrew as the supported installation route; direct release ZIPs
are not notarized. The official Homebrew client is installed here at version 0.0.14:

```sh
brew install openai/tools/tunnel-client
tunnel-client --version
tunnel-client help quickstart
```

Only after Platform tunnel access is verified and the tunnel ID and Restricted runtime key
are provisioned, use a local loopback-only Career Search MCP server. Set
`CAREER_AUTH_MODE=local`, `CAREER_READ_ONLY=false` (or `true` to restrict writes), and
`MCP_HOST=127.0.0.1` in the untracked
`.env` file. Do not put local/no-auth mode behind a generic public tunnel. Start the MCP
server and watcher as separate processes using the same `CAREER_DB_PATH`:

```sh
.venv/bin/career-search-mcp
.venv/bin/career-watcher --once
# Keep the watcher running for scheduled refreshes instead:
.venv/bin/career-watcher
```

For a long-lived local runtime, use the managed `runtimes connect` command instead of
`nohup`, `disown`, or manually running a profile. Attach to the existing tunnel with its ID
and the target workspace ID; use `--workspace-id` without `--organization-id`. Supply the
Restricted runtime key as a file reference, never as a literal key value:

```sh
tunnel-client runtimes connect \
  --alias career-search \
  --profile career-search \
  --profile-dir "<private profile directory>" \
  --tunnel-id "<existing Career Search tunnel ID>" \
  --workspace-id "<target ChatGPT workspace ID>" \
  --runtime-api-key "file:/path/to/restricted-runtime-key" \
  --mcp-server-url http://127.0.0.1:8383/mcp
tunnel-client doctor --profile career-search --profile-dir "<private profile directory>" --explain
tunnel-client runtimes status career-search --json
```

For a new setup, enable Developer Mode, create a custom app from Settings → Apps, choose
Tunnel as the connection, and select or paste the tunnel ID. Here, the Career Search MCP
app is connected and verified. Open a fresh Chat conversation, choose Career Search MCP
from Add files and more, and ask it to search saved support-engineering jobs.
`search_saved_jobs` returns saved-listings-only coverage; the watcher refreshes sources. The same local SQLite path must be used by the server and watcher.
No Pro plan upgrade, purchase, account change, tunnel creation, or key creation is performed
automatically by these instructions.

See OpenAI's [Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels),
[onboarding guide](https://github.com/openai/tunnel-client/blob/master/docs/onboarding.md),
[permissions guide](https://github.com/openai/tunnel-client/blob/master/docs/permissions.md),
and [end-user guide](https://github.com/openai/tunnel-client/blob/master/docs/end-user-guide.md)
for current CLI syntax, key roles, networking, and troubleshooting.

### Adzuna API credentials

Adzuna is optional and uses its official API; it does not scrape job pages. Register through
the [Adzuna Developer signup](https://developer.adzuna.com/signup). The current form requires
account details, an organisation/group name and website, the intended API application, and
average monthly visitors; accept Adzuna's terms. The public docs say registration provides
an `app_id` and `app_key`. If the required organisation or website fields do not fit a
personal project, ask Adzuna how to register; do not invent organization details.

Store the issued values in the untracked local `.env` file or a deployment secret manager:

```dotenv
ADZUNA_APP_ID=<issued app id>
ADZUNA_APP_KEY=<issued app key>
```

Add `adzuna` to `CAREER_SOURCES` to enable it. The adapter calls Adzuna's official GB search
endpoint (`https://api.adzuna.com/v1/api/jobs/gb/search/1`) and requires both credentials.
The [Adzuna API overview](https://developer.adzuna.com/overview) documents those required
parameters and JSON response format. Trevor completed registration; the existing AWS
deployment was configured privately and verified on 19 September 2026. See
[verification results](verification.md) for actual MCP, watcher and ChatGPT checks.

## Connect Stage 1 sources in ChatGPT

Current provider documentation:
[Himalayas](https://himalayas.app/docs/remote-jobs-mcp),
[Scout](https://www.agentco.in/connect).

1. Open the current ChatGPT Plugins UI and choose Create app. OpenAI's current Help Center
   calls this Settings -> Apps -> Create; Pro users must enable Developer Mode under
   Settings -> Apps -> Advanced Settings. Name it `Himalayas Remote Jobs`.
2. Choose Server URL `https://mcp.himalayas.app/mcp`, authentication `No Auth` for public
   search. Create and Connect. This server advertises employer/profile/write tools too;
   use only `search_jobs`, `get_jobs`, `get_job_details` and other relevant public reads.
   Do not authorize a Himalayas account or enable employer writes for this workflow.
3. Create `Scout Job Search`, Server URL `https://agentco.in/api/mcp-remote`, authentication
   OAuth. Let ChatGPT perform its supported registration/PKCE flow; use the exact
   callback shown there. Provider documentation says no Scout account is required, but
   an OAuth handshake is still required by the live endpoint.
4. Select the connected integration explicitly from the chat's Plugins/tools menu (called
   Apps in the current Help Center). An app
   listed in settings may not be callable in an existing conversation automatically.
5. Ask for actual read-only source calls using the verification prompt below. Expand
   the tool activity and confirm results or a real empty search response from that source.

Suggested verification prompt:

> Use only this selected plugin's read-only discovery tool. Search recent Technical
> Support Engineer, Support Engineer, Product Support and Customer Engineer jobs eligible
> for UK, EMEA or worldwide remote. Prefer annual GBP £40k+ when disclosed; retain salary
> unknown. Exclude temporary/contract and clearly lower-paid roles. Report the actual tool
> and arguments and three representative jobs with URLs, dates and eligibility uncertainty.
> Do not browse as a substitute, update a profile, apply, save jobs or send messages.

Scout's own `scout_score` is not used by Career Search MCP. All reasoning remains in ChatGPT.

## Connect the finished Career Search MCP

Choose the tool flow that matches the intended server permissions.

### Refresh the existing connection

1. Verify the private tunnel and MCP service are healthy. Keep the MCP listener on
   `127.0.0.1`; do not expose local/no-auth mode through a public endpoint.
2. In ChatGPT Plugins, open the existing Career Search MCP connection and choose Refresh.
   See [OpenAI's connection guide](https://developers.openai.com/plugins/deploy/connect-chatgpt).
3. Inspect the refreshed tool list. Full mode must show 18 tools, including `search_jobs`,
   `save_profile`, `update_status`, `import_job_evidence`, and `mark_as_applied` as writes.
   Optional read-only mode must show 12 tools and exclude all five writes.
4. Select Career Search MCP in each target conversation. Verify a real read such as
   `get_job_detail`. If tool metadata is stale, follow the connection guide's fresh-chat
   verification procedure; do not assume that refreshing settings updates every runtime.
5. For write access, use an authorised, controlled record update and read it back. An
   idempotent `mark_as_applied` call for an already-confirmed submission can verify the
   route without inventing a new application. Respect ChatGPT's write confirmation flow.
   Check `get_job_detail` and `get_job_history` for the expected persistent result.
6. Verify both career agents separately. An unattended scheduled run needs a separate
   execution test; leave its timing and enabled state unchanged during connection checks.

### New read-only connection

Create a custom app in Developer Mode and choose the provisioned private tunnel. Set
`CAREER_READ_ONLY=true` before starting the service, then verify the 12-tool inventory.
Test `search_saved_jobs` for stored listings and `search_live_jobs` for request-time source
results, including per-source fetch times, failures and truncation. Live IDs are temporary.
`score_fit`, `tailor_resume`, `cover_letter_brief`, and `build_profile` prepare evidence;
none saves a reviewed profile. Use full mode or the authorised host-only admin route for
persistent changes.

### New write-enabled connection

Set `CAREER_READ_ONLY=false` and use the private tunnel or the secure public OAuth
deployment above. For public OAuth, connect to `https://YOUR-HOST/mcp`, complete the
identity provider's sign-in, and verify the owner subject and `career:access` scope.
Follow the same 17-tool inventory and controlled write/read-back checks described above.

`save_profile` saves reviewed factual evidence. `import_job_evidence` persists external
plugin evidence. `update_status` changes the tracked lifecycle. `mark_as_applied` records
an explicitly confirmed past submission; it never submits one. `search_jobs` discovers
and saves listings. No tool sends a message or submits an application.

Do not report either route as connected until the relevant tool calls succeed inside
ChatGPT. A successful local test, the presence of a Tunnel option, or published plan
documentation does not prove this account's live connection or scheduled write support.
