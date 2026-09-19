# Security

This is a private, single-user MCP service. Default OAuth mode refuses to start without
HTTPS issuer/JWKS/public URL and the owner's immutable subject identifier. FastMCP checks
RS256 signatures, issuer, audience, expiration and required `career:access` scope. The
owner verifier additionally requires expiration, validates not-before, and rejects other
subjects even from the same tenant. The application ignores caller-supplied X-User-ID
and X-User-Email headers entirely. OAuth PKCE, consent and client registration belong to
the external authorization server, not a handwritten password/token implementation here.

All production requests require authentication. The default bind is loopback. The container
can bind internally while its host port remains loopback-only behind an HTTPS proxy.
Local mode is explicitly unauthenticated and must never be exposed by a generic public tunnel.
A private Secure MCP Tunnel still needs access restricted to the intended ChatGPT account
and a separate explicit deployment decision; it has not been provisioned by this repository.

Outbound adapters use fixed public provider endpoints. The retained upstream URL validator
requires HTTPS and checks every resolved IP for global routability, including CGNAT,
IPv4-mapped IPv6, multicast, loopback and reserved addresses. HTTP fetching disables
automatic redirects and environment proxies; redirects are revalidated, origin changes
are refused, and credential-bearing requests may not redirect. Responses are bounded.
There is no caller-URL fetching tool. The upstream resolve/connect DNS-rebinding residual
risk remains documented; production egress restrictions provide additional defense.

Tokens and Adzuna keys come from environment variables. Source errors report only the
exception type; do not enable verbose HTTP logging (Adzuna credentials are query parameters).
Do not print OAuth bearer tokens. Profiles and job databases stay out of Git and Docker
build context. Resume text is stored locally and returned to the authorized ChatGPT caller,
never sent to job sources. Encrypt the host/volume and backups and restrict filesystem access.

Containers use uid/gid 1000, read-only root filesystems, dropped capabilities and
no-new-privileges. No database port is exposed. No SMTP, browser scraper or external LLM
credentials are required. Dependency audit runs in CI with no inherited vulnerability exemption.

Untrusted job text can contain prompt injections. Tool descriptions and evidence briefs
instruct ChatGPT to treat it only as data. Tool annotations do not themselves enforce user
intent; ChatGPT should confirm lifecycle/profile writes as appropriate. No application or
messaging endpoint exists in this server.

Report suspected vulnerabilities privately through the repository owner's GitHub profile.
Avoid including personal data or active secrets in reports.
