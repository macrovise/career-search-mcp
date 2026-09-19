# Local development, secure hosting and ChatGPT connection

## Do you need hosting?

ChatGPT needs a route to the running MCP server. That can be a server on a hosting
provider, or your Mac through OpenAI's private Secure MCP Tunnel if available for
your account. A local command alone is not a ChatGPT connection. With the Mac option,
it must stay powered on, awake and connected for searches and the watcher to run.
No hosting subscription, tunnel, identity tenant, paid resource or persistent system
service has been provisioned by this repository.

Start with local validation (README). For production, the supported public-server
configuration uses a persistent volume, HTTPS reverse proxy, and an external OAuth
provider. Do not expose local/no-auth mode via a generic public tunnel.

## Environment

Copy `.env.example` to `.env` locally; do not commit it. The server and watcher read it.

| Variable | Use |
|---|---|
| CAREER_AUTH_MODE | `oauth` default, or `local` for trusted loopback tests only |
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

OpenAI documents [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
and the official [tunnel-client](https://github.com/openai/tunnel-client). The inspected
ChatGPT create-plugin form offers a Tunnel option. Availability in the form does not
prove that the account has a provisioned tunnel or runtime credentials.

For this route, first provision a private tunnel associated only with the intended
ChatGPT workspace/account, then install the official macOS client using the vendor's
Homebrew instructions. Configure it against the loopback server, with only the
necessary tunnel runtime permissions. Confirm tunnel readiness and access restrictions
before connecting profile data. This deployment path has not been tested here and no
tunnel credentials have been created. Do not confuse a private access-controlled tunnel
with a publicly accessible unauthenticated URL.

## Connect Stage 1 sources in ChatGPT

Current provider documentation:
[Himalayas](https://himalayas.app/docs/remote-jobs-mcp),
[Scout](https://www.agentco.in/connect).

1. Open ChatGPT -> Plugins -> Create app (the current UI may also expose this through
   Settings -> Plugins). Name it `Himalayas Remote Jobs`.
2. Choose Server URL `https://mcp.himalayas.app/mcp`, authentication `No Auth` for public
   search. Create and Connect. This server advertises employer/profile/write tools too;
   use only `search_jobs`, `get_jobs`, `get_job_details` and other relevant public reads.
   Do not authorize a Himalayas account or enable employer writes for this workflow.
3. Create `Scout Job Search`, Server URL `https://agentco.in/api/mcp-remote`, authentication
   OAuth. Let ChatGPT perform its supported registration/PKCE flow; use the exact
   callback shown there. Provider documentation says no Scout account is required, but
   an OAuth handshake is still required by the live endpoint.
4. Select the connected plugin explicitly from the chat's Plugins/tools menu. A plugin
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

After deploying and verifying authentication:

1. ChatGPT -> Plugins -> Create app -> name `Career Search MCP`.
2. Server URL: `https://YOUR-HOST/mcp`; authentication: OAuth.
3. Complete your identity provider's sign-in/consent. Verify the account's subject matches
   `OAUTH_OWNER_SUBJECT` and the granted scope is `career:access`.
4. Review the discovered tools. Select Career Search MCP in the target conversation.
5. Run `get_profile`, then `search_jobs` with `Technical Support Engineer` and inspect
   per-source status. Ask for `score_fit`, `tailor_resume` and `cover_letter_brief` for a
   returned canonical job ID. Search again and confirm one record with retained provenance.
6. Supply your actual résumé to `build_profile`; review ChatGPT's extracted facts and quotes
   before saving. Initial preferences do not contain claimed skills or work authorization.
7. For a user-selected role, record `interesting`, then restart the service and verify
   persistence with `get_my_jobs` and `get_job_history`.

Do not report the system connected until those calls succeed inside ChatGPT. Do not
mark applied just because the application brief has been prepared.
