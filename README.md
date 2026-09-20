# Career Search MCP

A personal job-search evidence service for ChatGPT, forked from
[TadMSTR/jobsearch-mcp](https://github.com/TadMSTR/jobsearch-mcp).
ChatGPT does the reasoning and writing. This server discovers jobs, records provenance,
deduplicates listings, prepares evidence, and tracks the application lifecycle.
It never calls an LLM, submits an application, or sends a message.

## Start locally

Python 3.11+ is required. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
CAREER_AUTH_MODE=local .venv/bin/career-search-mcp
```

This starts Streamable HTTP at `http://127.0.0.1:8383/mcp`. Local mode refuses a
non-loopback bind. It is for trusted local clients only; do not expose it through
a generic public tunnel. The default mode is OAuth and fails closed without configuration.

In another terminal, exercise the real local HTTP transport:

```sh
.venv/bin/python scripts/smoke_mcp.py http://127.0.0.1:8383/mcp
```

Run the watcher once, or leave it running with its six-hour interval:

```sh
.venv/bin/career-watcher --once
.venv/bin/career-watcher
```

The watcher stores discoveries and marks explicitly scheduled follow-ups due.
It never marks a job applied, infers rejection from a missing search result, or sends email.
It runs only while this process is running; no background system service is installed automatically.

## ChatGPT read and write access

[OpenAI's Developer Mode documentation](https://developers.openai.com/api/docs/guides/developer-mode)
supports read and write MCP tools on ChatGPT Pro. Write actions require confirmation by
default. `CAREER_READ_ONLY=false` exposes 18 tools: 12 reads and five writes:
`search_jobs`, `save_profile`, `update_status`, `import_job_evidence`, and `mark_as_applied`.
These writes save career records; none submits an application or contacts an employer.

On 20 September 2026, the existing AWS service was switched to full mode and its 17-tool
inventory was verified directly. Refreshing the ChatGPT connection and verifying a write
followed by a read-back in both career agents remain separate, pending checks. Backend
activation alone does not establish that ChatGPT or an unattended scheduled run can write.

`CAREER_READ_ONLY=true` remains an optional restriction, independent of the Pro plan.
Its 12-tool surface includes `search_saved_jobs` for stored records and `search_live_jobs`
for on-demand queries without persistence. The four evidence and writing-preparation
tools remain available in either mode. Earlier nine- and ten-tool ChatGPT checks are
historical evidence only. See [verification status](docs/verification.md) and
[connection instructions](docs/deployment.md).

No tunnel, API key, Adzuna account, subscription change, or deployment is provisioned
automatically. Optional Adzuna credentials require registration with the
[Adzuna developer site](https://developer.adzuna.com/signup); setup details are in the
deployment guide.

## Shared career agents

The shared result contract adds HTTP Status, Eligibility/Compatibility, estimated ATS
keyword coverage, Fetched_at and Source to each role. Existing job plugins can pass
evidence to `assess_job_evidence` without network calls or persistence.
`prepare_handoff` exports portable evidence for the other agent. In full mode, MCP write
tools save reviewed profiles, import evidence, and update lifecycle/submission records.
The authorised host-only `career-admin` command remains an alternative.
Two CV variants share one factual profile. See [agent integration](docs/agent-integration.md)
for the evidence contract and historical read-only handoff limitations. End-to-end write
verification is still required before treating the agents as write-enabled.

## Development checks

```sh
.venv/bin/pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/python -m pip check
```

Mocked source tests require no credentials. The smoke script performs live public
searches and writes job listings to the configured local database, but sends no résumé.
Failures from individual providers appear explicitly in `source_status`.

## Architecture and documentation

- [Architecture, schema, matching, lifecycle, and source precedence](docs/architecture.md)
- [Secure deployment, configuration, and ChatGPT connection](docs/deployment.md)
- [Source status and verification limits](docs/verification.md)
- [Security policy](SECURITY.md)

SQLite with WAL is the only datastore. MCP and one watcher share a local persistent
volume. No Postgres, Qdrant, Valkey, Ollama, Anthropic, Firecrawl, SMTP, or scraping
service is required. This is a single-user, single-host deployment, not a distributed service.

## Upstream maintenance

The repository retains upstream history and MIT attribution. Use separate remotes:

```sh
git remote -v
git fetch upstream
git log --oneline HEAD..upstream/main
# Review individual fixes before selectively applying them:
git cherry-pick <reviewed-commit>
```

`origin` points to `macrovise/career-search-mcp`; `upstream` points to
`TadMSTR/jobsearch-mcp`. The custom branch is `feat/career-search-chatgpt`.
Do not blindly merge upstream's former Claude, identity-header, or scraping paths.
The previous implementation and tests remain recoverable in Git history.
